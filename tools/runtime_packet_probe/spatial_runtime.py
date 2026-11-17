# -*- coding: utf-8 -*-
"""Game-side adapters for the two-dimensional and split-uniform experiments."""
from .aggregate_runtime import AggregateProbe


class SpatialProbe(AggregateProbe):
    def __init__(self, post, config, seed):
        config = dict(config)
        if config['transport'] == 'uniform_split':
            config.setdefault('target_pixels', list(config['screen_size']))
        if config.get('query') is None:
            config['query'] = [float(config['pages']), 0., 0., 0.]
        AggregateProbe.__init__(self, post, config, seed)

    def _restore_parameters(self):
        transport = self.config['transport']
        parameter = 'page' if transport == 'atlas2d' else 'tile'
        values = (self.config['page_uniforms'] if transport == 'atlas2d'
                  else self.config['metadata_values'])
        for name, value in zip(self.config['producer_names'], values):
            if not self.post.SetParameter(name, parameter, value):
                raise RuntimeError('Spatial metadata upload rejected: '+name)
        if transport != 'atlas2d':
            return
        self.select(*self.query[1:])
        name = self.config['display_name']
        for parameter, value in (('display_rect', self.config['display_rect_norm']),
                                 ('atlas_layout', self.config['display_layout'])):
            if not self.post.SetParameter(name, parameter, value):
                raise RuntimeError('Spatial display upload rejected: '+parameter)

    def select(self, start=0, count=None, word_shift=0):
        if self.config['transport'] != 'atlas2d':
            raise RuntimeError('Split uniform output has no atlas query')
        pages = self.config['pages']
        if count is None:
            count = min(128, pages)
        if (int(start) != start or int(count) != count or int(word_shift) != word_shift or
                start < 0 or start >= pages or count < 1 or count > pages or
                abs(word_shift) > 1024):
            raise ValueError('Invalid spatial display window')
        query = [float(pages), float(start), float(count), float(word_shift)]
        if not self.post.SetParameter(self.config['display_name'], 'query', query):
            raise RuntimeError('Spatial query rejected')
        self.query = query

    def snapshot(self):
        result = AggregateProbe.snapshot(self)
        result['transport'] = self.config['transport']
        result['shader_mode'] = self.config.get('shader_mode', 'shared')
        result['screen_size'] = self.config['screen_size']
        result['metadata_parameter'] = ('page' if self.config['transport'] == 'atlas2d'
                                        else 'tile')
        if self.config['transport'] == 'atlas2d':
            result['aggregate']['layout'] = self.config['layout']
        else:
            result['rectangles_norm'] = self.config['rectangles_norm']
            result['aggregate']['query'] = None
        return result
