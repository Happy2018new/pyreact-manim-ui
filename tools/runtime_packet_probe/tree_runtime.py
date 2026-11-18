# -*- coding: utf-8 -*-
"""Game-side five-way atlas tree with bounded incremental leaf uploads."""
import math
import time

from .aggregate_runtime import AggregateProbe
from .isolated_runtime import IsolatedProbe
from .runtime import dataset


class TreeProbe(IsolatedProbe):
    def __init__(self, post, config, seed):
        self.initial_seed = None
        self.initialized = False
        self.payload_consistent = True
        self.cursor = 0
        self.update_budget_bytes = 3072
        self.update_history = []
        self.history_complete = True
        self.update_count = 0
        self.initialization_timing = None
        IsolatedProbe.__init__(self, post, config, seed)

    @staticmethod
    def _vec4(values):
        return (isinstance(values, (list, tuple)) and len(values) == 4 and
                all(type(value) in (int, float) and not math.isnan(value) and
                    not math.isinf(value) for value in values))

    def _validate_config(self):
        config = self.config
        pages, payload = config['pages'], config['payload_bytes']
        if (config['transport'] != 'tree_atlas' or type(pages) is not int or
                type(payload) is not int or payload < 1 or pages != (payload+35)//36 or
                self.words_per_page != 12 or config.get('bytes_per_page', 36) != 36):
            raise ValueError('Tree atlas requires twelve words per 36-byte leaf')
        leaves, producers = config['leaf_names'], config['producer_names']
        merges = config['merge_parameters']
        if (len(leaves) != pages or producers[:pages] != leaves or
                not isinstance(merges, dict) or set(producers[pages:]) != set(merges)):
            raise ValueError('Tree producer identities must be leaves followed by merges')
        expected = [config['saved_scene_name']] + list(producers) + [config['display_name']]
        if (len(set(expected)) != len(expected) or
                [process['name'] for process in config['processes']] != expected):
            raise ValueError('Tree process order must be save, leaves, merges, consumer')
        if len(config['query']) != 4 or not self._vec4(config['display_layout']):
            raise ValueError('Tree consumer requires query and atlas layout vec4 values')
        if config['display_layout'][2:] != [payload, 0]:
            raise ValueError('Tree consumer layout must describe requested payload bytes')
        definitions = dict((process['name'], process) for process in config['processes'])
        for name in leaves:
            parameters = definitions[name].get('paras', [])
            if (set(value['name'] for value in parameters) != set(('packet0', 'packet1', 'packet2')) or
                    len(parameters) != 3 or any(not self._vec4(value['value']) for value in parameters)):
                raise ValueError('Tree leaf must contain exactly three payload vec4 parameters: '+name)
        for name in merges:
            parameters = definitions[name].get('paras', [])
            if (len(parameters) != 2 or set(value['name'] for value in parameters) != set(('node', 'layout'))):
                raise ValueError('Tree merge must contain node and layout parameters: '+name)
        self._validate_tree_edges(expected)

    def _validate_tree_edges(self, expected):
        config = self.config
        producers = config['producer_names']
        positions = dict((name, index) for index, name in enumerate(expected))
        incoming = dict((name, []) for name in config['merge_parameters'])
        outgoing = dict((name, 0) for name in producers)
        consumer_inputs = {}
        for edge in config['connections']:
            if (len(edge) != 5 or edge[0] not in positions or edge[2] not in positions or
                    positions[edge[0]] >= positions[edge[2]] or edge[1] != 0 or edge[3] != 0):
                raise ValueError('Tree edges must connect forward between owned pass zero outputs')
            source, target, slot = edge[0], edge[2], edge[4]
            if source in outgoing:
                outgoing[source] += 1
            if target == config['display_name'] and slot in (3, 4) and slot not in consumer_inputs:
                consumer_inputs[slot] = source
            elif target in incoming and source in outgoing and type(slot) is int and 3 <= slot <= 7:
                incoming[target].append((slot, source))
            else:
                raise ValueError('Invalid or duplicate tree input: '+repr(edge))
        if (set(consumer_inputs) != set((3, 4)) or
                consumer_inputs[4] != config['saved_scene_name'] or
                consumer_inputs[3] not in outgoing or any(value != 1 for value in outgoing.values())):
            raise ValueError('Every tree producer needs one parent and consumer needs root plus saved scene')
        spans = dict((name, (index, 1, 1)) for index, name in enumerate(config['leaf_names']))
        for name in producers[config['pages']:]:
            children = sorted(incoming[name])
            if not children or [slot for slot, source in children] != list(range(3, 3+len(children))):
                raise ValueError('Tree merge inputs must occupy consecutive sampler slots: '+name)
            parameters = config['merge_parameters'][name]
            node, layout = parameters.get('node'), parameters.get('layout')
            if (not self._vec4(node) or not self._vec4(layout) or
                    any(value != int(value) or value < 1 for value in node) or
                    layout != [config['screen_size'][1], 12, 0, 0]):
                raise ValueError('Invalid tree merge metadata: '+name)
            first, count = spans[children[0][1]][0], 0
            for slot, source in children:
                child_first, child_count, child_capacity = spans[source]
                if child_first != first+count or child_capacity != node[2]:
                    raise ValueError('Tree child ranges or capacities are not contiguous: '+name)
                count += child_count
            if node[3] != count or node[0]*node[1] < count*12:
                raise ValueError('Tree merge dimensions or page count lose payload: '+name)
            spans[name] = (first, count, int(node[2])*5)
        root = consumer_inputs[3]
        if config.get('root_name', root) != root:
            raise ValueError('Tree root identity does not match consumer input')
        if spans[root][:2] != (0, config['pages']):
            raise ValueError('Tree root must contain every leaf exactly once')
        if root in config['merge_parameters']:
            root_size = config['merge_parameters'][root]['node'][:2]
        else:
            root_size = [12, 1]
        if config['display_layout'][:2] != root_size:
            raise ValueError('Tree consumer dimensions do not match root output')

    def _restore_parameters(self):
        for name in self.config['producer_names']:
            parameters = self.config['merge_parameters'].get(name)
            if parameters is None:
                continue
            for parameter in ('node', 'layout'):
                if not self.post.SetParameter(name, parameter, parameters[parameter]):
                    raise RuntimeError('Tree merge parameter upload failed: '+name+'/'+parameter)
        name = self.config['display_name']
        for parameter, value in (('query', self.query),
                                 ('display_rect', self.config['display_rect_norm']),
                                 ('atlas_layout', self.config['display_layout'])):
            if not self.post.SetParameter(name, parameter, value):
                raise RuntimeError('Tree consumer parameter upload failed: '+parameter)

    def set_update_budget(self, byte_count):
        if type(byte_count) is not int or not 36 <= byte_count <= 3072:
            raise ValueError('Tree update budget must be an integer from 36 to 3072 bytes')
        self.update_budget_bytes = byte_count

    def write(self, seed):
        if self.error is not None:
            raise RuntimeError('Finish tree setup before uploading after a failure')
        if not self.payload_consistent:
            raise RuntimeError('Create a new TreeProbe after a partial payload upload failure')
        seed = int(seed)
        started = time.clock()
        initialize = not self.initialized
        pages = self.config['pages']
        first = 0 if initialize else self.cursor
        count = pages if initialize else min(pages, self.update_budget_bytes//36)
        # Generate only the selected leaves, even when their destination wraps.
        rows = dataset(seed, count*4)
        flat = [word for row in rows for word in row]
        words = [flat[offset:offset+12] for offset in range(0, count*12, 12)]
        packets = [[tuple(word/16777216. for word in page[offset:offset+4])
                    for offset in (0, 4, 8)] for page in words]
        first_count = min(count, pages-first)
        segments = [(first, first_count)]
        if first_count < count:
            segments.append((0, count-first_count))
        packed = time.clock()
        offset = 0
        try:
            for start, length in segments:
                for index in range(start, start+length):
                    name = self.config['leaf_names'][index]
                    for packet_index, packet in enumerate(packets[offset]):
                        if not self.post.SetParameter(name, 'packet%d' % packet_index, packet):
                            raise RuntimeError('Tree payload upload failed: '+name)
                    offset += 1
        except Exception as error:
            # Some native leaves may contain the new generation. Never claim
            # the last committed host words describe that partial native state.
            self.payload_consistent = False
            self._failed(error)
            raise
        uploaded = time.clock()
        generation_ms, upload_ms = (packed-started)*1000., (uploaded-packed)*1000.
        if initialize:
            self.words = words
            self.initial_seed = int(seed)
            self.initialized = True
            self.initialization_timing = {'generation_ms': generation_ms, 'upload_ms': upload_ms}
        else:
            record = {'seed': int(seed), 'first_leaf': first, 'leaf_count': count,
                      'actual_storage_bytes': count*36, 'budget_bytes': self.update_budget_bytes,
                      'generation_ms': generation_ms, 'upload_ms': upload_ms}
            self._commit_update(words, segments, record)
        return generation_ms, upload_ms

    def _commit_update(self, words, segments, record):
        offset, valid_bytes = 0, 0
        for start, length in segments:
            self.words[start:start+length] = words[offset:offset+length]
            offset += length
            valid_bytes += max(0, min(length*36, self.config['payload_bytes']-start*36))
        record['valid_payload_bytes'] = valid_bytes
        self.update_count += 1
        if len(self.update_history) < 512:
            self.update_history.append(record)
        else:
            self.history_complete = False
        self.cursor = (record['first_leaf']+record['leaf_count']) % self.config['pages']

    def snapshot(self):
        result = AggregateProbe.snapshot(self)
        result.update({'transport': self.config['transport'],
                       'screen_size': self.config['screen_size'],
                       'payload_bytes': self.config['payload_bytes'],
                       'initial_seed': self.initial_seed, 'initialized': self.initialized,
                       'payload_consistent': self.payload_consistent,
                       'update_budget_bytes': self.update_budget_bytes, 'cursor': self.cursor,
                       'update_history': [dict(record) for record in self.update_history],
                       'history_complete': self.history_complete, 'update_count': self.update_count,
                       'initialization_timing': self.initialization_timing})
        result['aggregate']['layout'] = self.config['layout']
        return result
