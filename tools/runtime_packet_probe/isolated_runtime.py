# -*- coding: utf-8 -*-
"""Game-side lifecycle for an atlas isolated from the saved scene colour."""
import math
import time
import traceback

from .aggregate_runtime import AggregateProbe


class IsolatedProbe(AggregateProbe):
    """Register disabled passes, then connect them before any pass can render.

    The caller owns render-callback scheduling and any active benchmark writer.
    Payload generation and the two vec4 uploads per page use AggregateProbe.
    """
    def __init__(self, post, config, seed):
        # AggregateProbe.__init__ enables passes immediately, so deliberately
        # initialise only its state here and reuse its payload writer.
        self.post = post
        self.config = dict(config)
        self.words = []
        self.names = []
        self.enabled = False
        self.ready = False
        self.error = None
        self.cleanup_errors = []
        self.connections = []
        self.seed = seed
        self.words_per_page = config.get('words_per_page', 8)
        self.setup_ms = 0.
        self._validate_config()
        self.query = self._query_values(*config['query'])
        started = time.clock()
        try:
            present = set(self.post.GetPostProcessOrder() or [])
            for process in config['processes']:
                name = process['name']
                # A rejected/raising registration may already have mutated the
                # engine. Keep that name owned so cleanup cannot abandon it.
                self.names.append(name)
                if name not in present:
                    definition = dict(process)
                    definition['enable'] = False
                    if not self.post.AddPostProcess(definition):
                        raise RuntimeError('Process registration failed: '+name)
            errors = self._disable_all()
            if errors:
                raise RuntimeError('; '.join(errors))
        except Exception as error:
            self._failed(error)
            error.aggregate_probe = self
            raise
        finally:
            self.setup_ms += (time.clock()-started)*1000.

    def _validate_config(self):
        config = self.config
        pages, payload = config['pages'], config['payload_bytes']
        if (config['transport'] != 'isolated_atlas' or
                type(pages) is not int or type(payload) is not int or
                payload < 1 or pages != (payload+23)//24 or self.words_per_page != 8):
            raise ValueError('Isolated atlas requires eight words per 24-byte page')
        if (len(config['producer_names']) != pages or
                len(config['page_uniforms']) != pages):
            raise ValueError('Producer metadata count does not match page count')
        expected = ([config['saved_scene_name']] + list(config['producer_names']) +
                    [config['display_name']])
        if (len(set(expected)) != len(expected) or
                [process['name'] for process in config['processes']] != expected):
            raise ValueError('Process order must be save, producers, consumer with unique names')
        if len(config['query']) != 4:
            raise ValueError('Isolated query requires four values')
        positions = dict((name, index) for index, name in enumerate(expected))
        for connection in config['connections']:
            if (len(connection) != 5 or connection[0] not in positions or
                    connection[2] not in positions or
                    positions[connection[0]] >= positions[connection[2]]):
                raise ValueError('Isolated connections must refer forward to owned processes')

    def _disable_all(self):
        owned = set(self.names)
        order = (list(self.config['producer_names']) +
                 [self.config['display_name'], self.config['saved_scene_name']])
        errors = []
        for name in order:
            if name not in owned:
                continue
            try:
                if not self.post.SetEnableByName(name, False):
                    errors.append('Process disable rejected: '+name)
            except Exception as error:
                traceback.print_exc()
                errors.append('%s: %s' % (name, error))
        self.cleanup_errors = errors
        self.enabled = None if errors else False
        if errors:
            self.ready = False
        return errors

    def _restore_parameters(self):
        for name, values in zip(self.config['producer_names'], self.config['page_uniforms']):
            if not self.post.SetParameter(name, 'page', values):
                raise RuntimeError('Page parameter upload failed: '+name)
        name = self.config['display_name']
        for parameter, values in (('query', self.query),
                                   ('display_rect', self.config['display_rect_norm']),
                                   ('atlas_layout', self.config['display_layout'])):
            if not self.post.SetParameter(name, parameter, values):
                raise RuntimeError('Isolated display upload rejected: '+parameter)

    def _verify_order(self):
        order = self.post.GetPostProcessOrder() or []
        positions = dict((name, index) for index, name in enumerate(order))
        if any(name not in positions for name in self.names):
            raise RuntimeError('New isolated processes are not present yet')
        indices = [positions[name] for name in self.names]
        if indices != sorted(indices):
            raise RuntimeError('Isolated postprocess order is not save, producers, consumer')

    def _enable_all(self):
        order = ([self.config['saved_scene_name'], self.config['display_name']] +
                 list(self.config['producer_names']))
        for name in order:
            if not self.post.SetEnableByName(name, True):
                raise RuntimeError('Process enable failed: '+name)
        self.enabled = True

    def finish(self):
        """Run in one later render callback, with all enabling at its end."""
        started = time.clock()
        self.ready = False
        self.error = None
        self.connections = []
        try:
            if self.enabled is not False:
                errors = self._disable_all()
                if errors:
                    raise RuntimeError('; '.join(errors))
            self._restore_parameters()
            self.write(self.seed)
            for connection in self.config['connections']:
                accepted = self.post.PostPassResultToOtherPass(*connection)
                self.connections.append(bool(accepted))
                if not accepted:
                    raise RuntimeError('Pass connection rejected: '+repr(connection))
            self._verify_order()
            self._enable_all()
            self.ready = True
            self.cleanup_errors = []
        except Exception as error:
            self._failed(error)
            raise
        finally:
            self.setup_ms += (time.clock()-started)*1000.
        return self.snapshot()

    def set_enabled(self, enabled):
        if not enabled:
            errors = self._disable_all()
            if errors:
                self.error = '; '.join(errors)
                raise RuntimeError(self.error)
            return
        if not self.ready or self.error is not None:
            raise RuntimeError('Finish isolated setup before enabling it')
        try:
            self._enable_all()
        except Exception as error:
            self._failed(error)
            raise

    def _query_values(self, mode=0, start=0, count=None, salt=7):
        payload = self.config['payload_bytes']
        if count is None:
            count = min(payload, 3072)
        values = (mode, start, count, salt)
        if any(type(value) not in (int, float) or math.isnan(value) or
               math.isinf(value) or int(value) != value for value in values):
            raise ValueError('Isolated query values must be finite integers')
        if mode not in (0, 1, 2) or not 0 <= start < payload or not 1 <= count <= 3072:
            raise ValueError('Invalid isolated display window')
        # A window may extend past the requested payload; the consumer writes
        # zero for its tail instead of wrapping or exposing page padding.
        return [float(value) for value in values]

    def select(self, mode=0, start=0, count=None, salt=7):
        query = self._query_values(mode, start, count, salt)
        try:
            if not self.post.SetParameter(self.config['display_name'], 'query', query):
                raise RuntimeError('Isolated query rejected')
        except Exception as error:
            self._failed(error)
            raise
        self.query = query

    def snapshot(self):
        result = AggregateProbe.snapshot(self)
        result.update({'transport': self.config['transport'],
                       'screen_size': self.config['screen_size'],
                       'payload_bytes': self.config['payload_bytes']})
        result['aggregate']['layout'] = self.config['layout']
        return result
