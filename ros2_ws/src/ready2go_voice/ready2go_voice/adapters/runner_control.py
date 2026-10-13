"""Current selected ROS Runner connection, not physical safety or authentication.

Jazzy MessageInfo is a dict without per-sample publisher_gid. Endpoint GID below
identifies the graph connection only. No handshake/control message is generated.
"""
from dataclasses import dataclass
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
        except (ValueError, TypeError):
            return None
        if isinstance(doc,dict) and doc.get('boot_id') in self.retired_boots:
            self.reason = 'runner_boot_retired'
            return None
        if (not isinstance(doc, dict) or not isinstance(doc.get('boot_id'), str)
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
