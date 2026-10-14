"""Current selected ROS Runner connection, not physical safety or authentication.

Jazzy MessageInfo is a dict without per-sample publisher_gid. Endpoint GID below
identifies the graph connection only. No handshake/control message is generated.
"""
from dataclasses import dataclass
from copy import deepcopy
import json


@dataclass(frozen=True)
class RunnerBinding:
    boot: str
    endpoint_gid: bytes


class RunnerSource:
    def __init__(self, publishers, topic, *, name='runner', namespace='/'):
        self.publishers, self.topic = publishers, topic
        self.name, self.namespace = name, namespace
        self.binding = None
        self.retired_boots = set()
        self.reason = 'runner_not_observed'
        self.sequences = {}

    def endpoint(self):
        try:
            infos = self.publishers(self.topic)
            if len(infos) != 1:
                self.reason = 'runner_missing_or_multiple'
                return None
            info = infos[0]
            if (info.node_name != self.name or info.node_namespace != self.namespace
                    or info.topic_type != 'std_msgs/msg/String'):
                self.reason = 'runner_endpoint_not_selected'
                return None
            gid = bytes(info.endpoint_gid)
            if not gid or not any(gid):
                self.reason = 'runner_endpoint_identity_missing'
                return None
            return gid
        except Exception:
            self.reason = 'runner_graph_unavailable'
            return None

    def observe(self, raw, info):
        # Actual four-key dict is accepted; timestamp/sequence is not B freshness.
        if not isinstance(info, dict):
            self.reason = 'runner_metadata_not_jazzy_dict'
            return None
        gid = self.endpoint()
        if gid is None:
            return None
        try:
            doc = json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            self.reason = 'runner_payload_invalid'
            return None
        if isinstance(doc,dict) and doc.get('boot_id') in self.retired_boots:
            self.reason = 'runner_boot_retired'
            return None
        if (not isinstance(doc, dict) or doc.get('phase') not in ('idle','running','halted')
                or not isinstance(doc.get('boot_id'), str)
                or not doc['boot_id'].strip() or type(doc.get('seq')) is not int
                or doc['seq'] < 0):
            self.reason = 'runner_boot_or_sequence_invalid'
            return None
        if doc['seq'] <= self.sequences.get(doc['boot_id'], -1):
            self.reason = 'runner_sequence_not_current'
            return None
        self.sequences[doc['boot_id']] = doc['seq']
        new = RunnerBinding(doc['boot_id'], gid)
        if self.binding is not None and self.binding.boot != new.boot:
            self.retired_boots.add(self.binding.boot)
        self.binding = new
        self.reason = None
        return new

    def check(self, binding):
        return self.binding == binding and self.endpoint() == binding.endpoint_gid


class RunnerMemory:
    """Read-only C memory. Graph/current W4 binding, never physical observation.

    State has no boot field. On restart/loss, require a new state receipt; the
    existing Jazzy source timestamp orders samples, not a freshness timeout.
    """
    def __init__(self, source, topic, *, items, places):
        self.source = source
        self.state_source = RunnerSource(source.publishers, topic,
            name=source.name, namespace=source.namespace)
        self.items, self.places = set(items), set(places)
        self.binding = self.last_binding = None
        self.state = self.pending = None
        self.state_gid = None
        self.minimum_stamp = self.last_stamp = 0
        self.seen_status = False
        self.last_state_gid, self.last_state_stamp = None, 0
        self.replay_floor = None
        self.expected_state_gid = None

    def invalidate(self):
        self.binding = None
        self.state = self.pending = None
        self.state_gid = None

    def observe_status(self, binding, info):
        previous = self.last_binding
        state_gid = self.state_source.endpoint()
        reconnecting = self.seen_status and (binding != previous or self.binding is None
            or state_gid != self.expected_state_gid)
        pending = self.pending
        if reconnecting:
            self.state = None
            self.state_gid = None
            stamp = info.get('source_timestamp') if isinstance(info, dict) else None
            self.minimum_stamp = stamp if type(stamp) is int and stamp > 0 else None
            self.last_stamp = 0
        self.binding = self.last_binding = binding
        self.seen_status = True
        self.pending = None
        self.expected_state_gid = state_gid
        if pending is not None:
            self._accept(*pending)
        # Only a newly created reader may receive the publisher's current
        # latched record after loss. Never restore our pre-loss local state.
        self.replay_floor = None
        if (reconnecting and binding == previous and self.last_state_gid is not None
                and state_gid == self.last_state_gid and self.minimum_stamp is not None
                and self.last_state_stamp > 0):
            self.replay_floor = self.last_state_stamp
        return reconnecting

    def begin_replay(self):
        if self.replay_floor is not None:
            self.minimum_stamp = self.replay_floor
        self.replay_floor = None

    def _accept(self, doc, gid, stamp, status_gid):
        if (self.binding is None or not self.source.check(self.binding)
                or status_gid != self.binding.endpoint_gid
                or self.expected_state_gid is not None and gid != self.expected_state_gid
                or self.state_source.endpoint() != gid
                or self.minimum_stamp is None or stamp < self.minimum_stamp
                or stamp < self.last_stamp):
            return False
        self.state, self.state_gid, self.last_stamp = deepcopy(doc), gid, stamp
        self.last_state_gid, self.last_state_stamp = gid, stamp
        self.expected_state_gid = gid
        return True

    def observe(self, raw, info):
        gid = self.state_source.endpoint()
        if gid is None or not isinstance(info, dict):
            self.state = self.pending = None
            return False
        try:
            doc = json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            self.state = self.pending = None
            return False
        valid = (isinstance(doc, dict) and isinstance(doc.get('located_in'), dict)
            and isinstance(doc.get('open'), dict)
            and all(isinstance(value, dict) for value in doc.values())
            and all(key in self.items and (value is None or isinstance(value, str)
                    and value in self.places | {'gripper'})
                    for key, value in doc['located_in'].items())
            and all(key in self.places and (value is None or type(value) is bool)
                    for key, value in doc['open'].items()))
        if not valid:
            self.state = self.pending = None
            return False
        stamp = info.get('source_timestamp', 0)
        stamp = stamp if type(stamp) is int and stamp >= 0 else 0
        # A candidate is not queryable until the selected current status agrees.
        # Keep it across callback ordering, including restart/loss, not just init.
        candidate = (deepcopy(doc), gid, stamp, self.source.endpoint())
        if self.pending is None or stamp >= self.pending[2]:
            self.pending = candidate
        if self._accept(*candidate):
            self.pending = None
            return True
        self.state = None
        return False

    def current(self):
        if self.binding is None and not self.seen_status:
            return None
        if self.binding is None or not self.source.check(self.binding):
            # Preserve a newly received candidate for the next status, not the
            # previous queryable state. Explicit control loss still clears all.
            self.binding = None
            self.state = None
            self.state_gid = None
            return None
        if self.state_gid is None:
            return None
        if self.state_source.endpoint() != self.state_gid:
            self.binding = None
            self.state = None
            self.state_gid = None
            return None
        return deepcopy(self.state)
