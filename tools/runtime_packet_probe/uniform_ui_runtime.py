# -*- coding: utf-8 -*-
"""Game-side direct uniform draws grouped into independently created UI nodes.

Call create_next() once per render turn, then finish() after every Create()
lifecycle callback has completed. No postprocess, image carrier or disk upload.
"""
import math
import time
import traceback
import mod.client.extraClientApi as api


ScreenNode = api.GetScreenNodeCls()
MASK = 16777215
REGISTERED_UI = {}


def _words(seed, pages):
    state = int(seed) & MASK
    result = []
    for page in range(pages):
        row = []
        for index in range(8):
            state = (state * 1664525 + 1013904223) & MASK
            row.append(state)
        result.append(row)
    return result


def _pack(words, pages):
    if not isinstance(words, (list, tuple)) or len(words) != pages:
        raise ValueError('Payload page count mismatch')
    integers = (int, type(1 << 64))
    for row in words:
        if not isinstance(row, (list, tuple)) or len(row) != 8:
            raise ValueError('Each page must contain exactly eight uint24 words')
        if any(isinstance(word, bool) or not isinstance(word, integers) or
               word < 0 or word > MASK for word in row):
            raise ValueError('Payload words must be uint24 integers')
    return [[tuple(value / 16777216. for value in row[offset:offset + 4])
             for offset in (0, 4)] for row in words]


class UniformUISlice(ScreenNode):
    def __init__(self, namespace, name, param):
        ScreenNode.__init__(self, namespace, name, param)
        self.expected_controls = int(param.get('uniform_ui_count', 64))
        self.controls = []
        self.ready = False
        self.error = None

    def Create(self):
        self.SetScreenVisible(False)
        for index in range(self.expected_controls):
            path = '/slot_%03d' % index
            parent = self.GetBaseUIControl(path)
            canvas = self.GetBaseUIControl(path + '/canvas')
            if parent is None or canvas is None:
                self.error = 'Missing uniform UI control: ' + path
                return
            parent.SetVisible(False, False)
            self.controls.append((parent, canvas, canvas.asNeteasePaperDoll()))
        self.ready = True

    def configure(self, screen_definition, config, actor, screen_size):
        if not self.ready or self.error is not None:
            raise RuntimeError('Uniform UI slice Create callback is incomplete')
        if len(self.controls) != screen_definition['count']:
            raise RuntimeError('Uniform UI slice control count mismatch')
        screen_width, screen_height = screen_size
        for local, controls in enumerate(self.controls):
            index = screen_definition['offset'] + local
            left, top, width, height = config['rectangles_norm'][index]
            parent, canvas, doll = controls
            parent.SetPosition((left * screen_width, top * screen_height))
            parent.SetSize((width * screen_width, height * screen_height))
            canvas.SetPosition((0., 0.))
            canvas.SetSize((width * screen_width, height * screen_height))
            identifier = config['identifiers'][index]
            ndc_rect = (2 * left - 1., 1. - 2 * top, 2 * width, 2 * height)
            if not actor.SetEntityUIExtraUniforms(identifier, 3, ndc_rect):
                raise RuntimeError('Uniform UI rectangle rejected: ' + identifier)
            if not doll.RenderEntity({'entity_identifier': identifier, 'scale': 1.,
                                      'render_depth': -15, 'init_rot_x': 0.,
                                      'init_rot_y': 0., 'init_rot_z': 0.}):
                raise RuntimeError('Uniform UI RenderEntity rejected: ' + identifier)
            parent.SetVisible(True, False)
        self.UpdateScreen(True)


class UniformUIProbe(object):
    def __init__(self, config, seed=12345):
        if (config.get('transport') != 'uniform_ui' or config.get('words_per_page') != 8 or
                config.get('pages') != len(config.get('identifiers', []))):
            raise ValueError('Invalid uniform UI probe configuration')
        self.config = config
        self.seed = seed
        self.screens = []
        self.words = []
        self.ready = False
        self.enabled = False
        self.closed = False
        self.error = None
        self.cleanup_errors = []
        self.setup_ms = 0.
        self.logical_screen_size = None
        self.source = None
        factory = api.GetEngineCompFactory()
        self.actor = factory.CreateActorRender(None)
        self.game = factory.CreateGame(api.GetLevelId())

    def _hide_all(self):
        errors = []
        for index, screen in enumerate(self.screens):
            if screen is None:
                continue
            try:
                screen.SetScreenVisible(False)
            except Exception as error:
                traceback.print_exc()
                errors.append('Hide slice %d: %s' % (index, error))
        self.cleanup_errors = errors
        self.enabled = None if errors else False
        return errors

    def _failed(self, error):
        traceback.print_exc()
        self.error = '%s: %s' % (type(error).__name__, error)
        self.ready = False
        self._hide_all()

    def create_next(self):
        """Create at most one 64-control screen; allow a render turn before next."""
        if self.closed or self.error is not None:
            raise RuntimeError('Cannot create a closed or failed uniform UI probe')
        index = len(self.screens)
        if index == len(self.config['screens']):
            return None
        definition = self.config['screens'][index]
        namespace, key = self.config['ui_namespace'], definition['key']
        started = time.clock()
        try:
            registration = (namespace, key)
            registered = REGISTERED_UI.get(registration)
            if registered is not None and registered != definition['definition']:
                raise RuntimeError('UI key was registered for a different definition')
            if registered is None:
                if not api.RegisterUI(namespace, key, self.config['runtime_class'], definition['definition']):
                    raise RuntimeError('Uniform UI registration rejected: ' + key)
                REGISTERED_UI[registration] = definition['definition']
            screen = api.CreateUI(namespace, key, {'isHud': 1, 'uniform_ui_count': definition['count']})
            if screen is None:
                raise RuntimeError('Uniform UI CreateUI rejected: ' + key)
            # Retain ownership before any further SDK call can fail.
            self.screens.append(screen)
            screen.SetScreenVisible(False)
            return screen
        except Exception as error:
            self._failed(error)
            raise
        finally:
            self.setup_ms += (time.clock() - started) * 1000.

    def create_all(self):
        """Convenience for controlled callers; create_next permits staged setup."""
        while self.create_next() is not None:
            pass
        return self.snapshot()

    def finish(self):
        if self.closed or self.error is not None:
            raise RuntimeError('Cannot finish a closed or failed uniform UI probe')
        if len(self.screens) != len(self.config['screens']):
            raise RuntimeError('Create every uniform UI slice before finish')
        # A pending lifecycle callback is retryable, rather than a failed probe.
        if any(not screen.ready and screen.error is None for screen in self.screens):
            raise RuntimeError('Uniform UI Create callbacks are still pending')
        started = time.clock()
        try:
            size = tuple(self.game.GetScreenSize())
            if len(size) != 2 or any(value <= 0 or math.isnan(value) or math.isinf(value) for value in size):
                raise RuntimeError('Invalid logical game screen dimensions')
            self.logical_screen_size = size
            for definition, screen in zip(self.config['screens'], self.screens):
                if screen.error is not None:
                    raise RuntimeError(screen.error)
                screen.configure(definition, self.config, self.actor, size)
            self.write(self.seed)
            self.ready = True
            self.set_enabled(True)
        except Exception as error:
            self._failed(error)
            raise
        finally:
            self.setup_ms += (time.clock() - started) * 1000.
        return self.snapshot()

    def write(self, seed, provided=None):
        if self.closed or self.error is not None:
            raise RuntimeError('Cannot upload to a closed or failed uniform UI probe')
        if self.logical_screen_size is None:
            raise RuntimeError('Finish uniform UI layout before uploading')
        started = time.clock()
        words = _words(seed, self.config['pages']) if provided is None else provided
        packets = _pack(words, self.config['pages'])
        packed = time.clock()
        try:
            for identifier, page in zip(self.config['identifiers'], packets):
                for uniform, packet in enumerate(page, 1):
                    if not self.actor.SetEntityUIExtraUniforms(identifier, uniform, packet):
                        raise RuntimeError('Uniform UI payload rejected: ' + identifier)
        except Exception as error:
            # A mixed generation is never left visible after a partial upload.
            self._failed(error)
            raise
        uploaded = time.clock()
        self.words = [list(row) for row in words]
        self.seed = seed
        self.source = 'in_game_python' if provided is None else 'provided_words'
        return ((packed - started) * 1000., (uploaded - packed) * 1000.)

    def set_enabled(self, enabled):
        if not enabled:
            errors = self._hide_all()
            if errors:
                raise RuntimeError('; '.join(errors))
            return
        if not self.ready or self.error is not None or self.closed:
            raise RuntimeError('Finish uniform UI setup before enabling it')
        try:
            for screen in self.screens:
                screen.SetScreenVisible(True)
            self.enabled = True
        except Exception as error:
            self._failed(error)
            raise

    def close(self):
        self.ready = False
        self.closed = True
        errors = []
        for index, screen in enumerate(self.screens):
            if screen is None:
                continue
            try:
                screen.SetScreenVisible(False)
                screen.SetRemove()
                self.screens[index] = None
            except Exception as error:
                traceback.print_exc()
                errors.append('Remove slice %d: %s' % (index, error))
        self.cleanup_errors = errors
        self.enabled = None if errors else False
        if errors:
            raise RuntimeError('; '.join(errors))

    def snapshot(self):
        result = {'transport': 'uniform_ui', 'shader_mode': 'shared',
                'screen_size': self.config['screen_size'],
                'target_pixels': list(self.config['screen_size']),
                'logical_screen_size': self.logical_screen_size,
                'rectangles_norm': self.config['rectangles_norm'],
                'aggregate': {'pages': self.config['pages'], 'words': self.words,
                              'words_per_page': 8, 'query': None,
                              'display_rect_norm': self.config['display_rect_norm']},
                'ready': self.ready, 'enabled': self.enabled, 'closed': self.closed,
                'error': self.error, 'cleanup_errors': list(self.cleanup_errors),
                'created_screens': sum(screen is not None for screen in self.screens),
                'screen_count': len(self.config['screens']),
                'cached_controls': sum(len(screen.controls) for screen in self.screens if screen is not None),
                'setup_ms': self.setup_ms, 'source': self.source,
                'gpu_verified': False,
                'draw_calls': self.config['pages'], 'fullscreen_passes': 0,
                'image_carriers': 0}
        if self.source == 'in_game_python':
            result['expected_seed'] = self.seed
        return result
