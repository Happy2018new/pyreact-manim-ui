# -*- coding: utf-8 -*-
"""Game-side data generator and public postprocess upload for the probe."""
import time
import traceback
from .runtime import dataset


class AggregateProbe(object):
    def __init__(self, post, config, seed):
        self.post = post
        self.config = config
        self.words = []
        self.names = []
        self.enabled = False
        self.ready = False
        self.error = None
        self.cleanup_errors = []
        self.connections = []
        self.query = list(config['query'])
        self.seed = seed
        self.words_per_page = config.get('words_per_page', 8)
        if self.words_per_page != 8:
            raise ValueError('Runtime packet atlas requires eight words per page')
        self.setup_ms = 0.
        started = time.clock()
        if len(config['producer_names']) != config['pages']:
            raise ValueError('Producer count does not match page count')
        try:
            present = self.post.GetPostProcessOrder() or []
            for process in config['processes']:
                # Retain even the current name if an SDK call partially mutates
                # engine state before raising. The failed object remains owned.
                self.names.append(process['name'])
                if process['name'] not in present:
                    definition = dict(process)
                    definition['enable'] = True
                    if not post.AddPostProcess(definition):
                        raise RuntimeError('Process registration failed: '+process['name'])
                if not post.SetEnableByName(process['name'], True):
                    raise RuntimeError('Process enable failed: '+process['name'])
            self.enabled = True
        except Exception as error:
            self.setup_ms = (time.clock()-started)*1000.
            self._failed(error)
            error.aggregate_probe = self
            raise
        self.setup_ms = (time.clock()-started)*1000.

    def _disable_all(self):
        errors = []
        for name in self.names:
            try:
                if not self.post.SetEnableByName(name, False):
                    errors.append('Process disable rejected: '+name)
            except Exception as error:
                traceback.print_exc()
                errors.append('%s: %s' % (name, error))
        self.cleanup_errors = errors
        # A rejected cleanup leaves the actual enabled state unknown.
        self.enabled = None if errors else False
        return errors

    def _failed(self, error):
        traceback.print_exc()
        self.error = '%s: %s' % (type(error).__name__, error)
        self.ready = False
        self._disable_all()

    def _restore_parameters(self):
        for page, name in enumerate(self.config['producer_names']):
            values = [float(page), float(self.config['pages']), float(self.words_per_page), 0.0]
            if not self.post.SetParameter(name, 'page', values):
                raise RuntimeError('Page parameter upload failed: '+name)
        self.select(*self.query[1:])
        if not self.post.SetParameter(self.config['display_name'], 'display_rect',
                                      self.config['display_rect_norm']):
            raise RuntimeError('Display rectangle upload failed')

    def finish(self):
        # Complete in a later render turn; installation may be deferred.
        started = time.clock()
        self.ready = False
        self.error = None
        self.connections = []
        try:
            present = self.post.GetPostProcessOrder() or []
            if any(name not in present for name in self.names):
                raise RuntimeError('New aggregate processes are not present yet')
            for name in self.names:
                if not self.post.SetEnableByName(name, True):
                    raise RuntimeError('Process enable failed: '+name)
            # Existing process definitions retain prior SetParameter values.
            self._restore_parameters()
            self.write(self.seed)
            for connection in self.config['connections']:
                accepted = self.post.PostPassResultToOtherPass(*connection)
                self.connections.append(bool(accepted))
                if not accepted:
                    raise RuntimeError('Pass connection rejected: '+repr(connection))
            self.enabled = True
            self.ready = True
            self.cleanup_errors = []
        except Exception as error:
            self._failed(error)
            raise
        finally:
            self.setup_ms += (time.clock()-started)*1000.
        return self.snapshot()

    def write(self, seed):
        if self.error is not None:
            raise RuntimeError('Finish aggregate setup before uploading after a failure')
        started = time.clock()
        total = self.config['pages'] * self.words_per_page
        rows = dataset(seed, (total + 2) // 3)
        flat = [value for row in rows for value in row]
        words = [flat[start:start+self.words_per_page]
                 for start in range(0, total, self.words_per_page)]
        packets = [[tuple(value/16777216. for value in page[offset:offset+4])
                    for offset in (0, 4)] for page in words]
        packed = time.clock()
        try:
            for name, page in zip(self.config['producer_names'], packets):
                for index, packet in enumerate(page):
                    if not self.post.SetParameter(name, 'packet%d' % index, packet):
                        raise RuntimeError('Aggregate parameter upload failed: '+name)
        except Exception as error:
            # A partial upload leaves mixed generations in the native state.
            # Disable every owned process and require setup before further use.
            self._failed(error)
            raise
        uploaded = time.clock()
        self.words = words
        return ((packed-started)*1000., (uploaded-packed)*1000.)

    def set_enabled(self, enabled):
        if not enabled:
            errors = self._disable_all()
            if errors:
                self.ready = False
                self.error = '; '.join(errors)
                raise RuntimeError(self.error)
            return
        if not self.ready or self.error is not None:
            raise RuntimeError('Finish aggregate setup before enabling it')
        try:
            for name in self.names:
                if not self.post.SetEnableByName(name, True):
                    raise RuntimeError('Postprocess enable state rejected: '+name)
            self.enabled = True
        except Exception as error:
            self._failed(error)
            raise

    def select(self, row_shift=0, word_shift=0, byte_shift=0):
        query = [float(self.config['pages']), float(row_shift), float(word_shift), float(byte_shift)]
        if not self.post.SetParameter(self.config['display_name'], 'query', query):
            raise RuntimeError('Query rejected')
        self.query = query

    def snapshot(self):
        return {'aggregate': {'pages': self.config['pages'], 'words': self.words,
                             'words_per_page': self.words_per_page,
                             'display_rect_norm': self.config['display_rect_norm'],
                             'query': self.query},
                'enabled': self.enabled, 'connections': self.connections,
                'ready': self.ready, 'error': self.error,
                'cleanup_errors': list(self.cleanup_errors), 'process_names': list(self.names),
                'setup_ms': self.setup_ms, 'target_pixels': self.config['target_pixels'],
                'source': 'in_game_python', 'gpu_verified': False}
