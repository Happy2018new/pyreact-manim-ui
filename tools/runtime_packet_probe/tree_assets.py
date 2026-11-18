"""Host-only assets for a five-way private-RT uniform tree.

Each leaf owns twelve uint24 words (36 bytes), using EXTRA_VECTOR1..3 only.
Every merge copies at most five smaller data textures into its own local RT.
The saved picture travels separately to the final consumer. Pixel statistics
describe requested targets, not measured native allocations or performance.
"""
import json
from pathlib import Path
import re
import shutil
import uuid


HERE = Path(__file__).resolve().parent
WORDS_PER_PAGE = 12
BYTES_PER_PAGE = 36
FANOUT = 5
DISPLAY_RECT = [0.05, 0.05, 0.90, 0.90]
PARAMETER_NAMES = ['packet0', 'packet1', 'packet2']
LEAF_MATERIAL = 'pmanim_tree_leaf'
MERGE_MATERIAL = 'pmanim_tree_merge'
SAVE_MATERIAL = 'pmanim_tree_save'
CONSUMER_MATERIAL = 'pmanim_tree_consumer'


def _layout(pages, screen_size):
    columns = (pages + screen_size[1] - 1) // screen_size[1]
    width = WORDS_PER_PAGE * columns
    height = (pages + columns - 1) // columns
    if width > screen_size[0]:
        raise ValueError('tree target width exceeds the physical screen')
    return width, height


def _pass(material, pixels, screen_size):
    # Keep an intended integer target from rounding just below that integer
    # when the ratio is transported as float32 and multiplied by screen size.
    ratios = [min(1.0, (pixels[index] + 0.25) / float(screen_size[index]))
              for index in (0, 1)]
    return {'render_target': {'width': ratios[0], 'height': ratios[1]},
            'material': material, 'depth_enable': False}


def _parameter(name, values, maximum):
    return {'name': name, 'value': list(values), 'range': [0.0, float(maximum)]}


def tree_config(payload_bytes=96, screen_size=(720, 1080), namespace=None):
    """Build forward-only leaves, merge levels and one final array consumer.

    A page is a leaf's twelve consecutive RGB word texels. Every subtree has
    the same row-major word layout: width=12*ceil(pages/screen_height), then
    height=ceil(pages/(width/12)). Merge children have capacity 5**(level-1)
    pages, except the last child may contain fewer pages. No scene channel is
    used to carry payload. Uniform uploads are performed by TreeProbe.
    """
    if type(payload_bytes) is not int or payload_bytes < 1:
        raise ValueError('payload_bytes must be a positive integer')
    if (not isinstance(screen_size, (tuple, list)) or len(screen_size) != 2 or
            any(type(value) is not int or value < 1 for value in screen_size)):
        raise ValueError('screen_size must contain two positive integer dimensions')
    screen_size = list(screen_size)
    pages = (payload_bytes + BYTES_PER_PAGE - 1) // BYTES_PER_PAGE
    root_width, root_height = _layout(pages, screen_size)
    namespace = namespace if namespace is not None else 'pmanim_tree_' + uuid.uuid4().hex[:16]
    if not isinstance(namespace, str) or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', namespace) is None:
        raise ValueError('namespace must be a nonempty ASCII process identifier')

    saved = namespace + '_saved_scene'
    display = namespace + '_display'
    processes = [{'name': saved, 'enable': False, 'paras': [],
                  'pass_array': [_pass(SAVE_MATERIAL, screen_size, screen_size)]}]
    leaf_names = [namespace + '_leaf_%05d' % page for page in range(pages)]
    producer_names, connections, merge_parameters, nodes = list(leaf_names), [], {}, []
    current = []
    for page, name in enumerate(leaf_names):
        processes.append({'name': name, 'enable': False,
                          'paras': [_parameter(parameter, [0.0] * 4, 1.0)
                                    for parameter in PARAMETER_NAMES],
                          'pass_array': [_pass(LEAF_MATERIAL, [WORDS_PER_PAGE, 1], screen_size)]})
        node = {'name': name, 'level': 0, 'first_page': page, 'pages': 1,
                'target_pixels': [WORDS_PER_PAGE, 1], 'children': []}
        current.append(node)
        nodes.append(node)
    levels = [{'level': 0, 'nodes': pages, 'passes': pages,
               'pixels': pages * WORDS_PER_PAGE, 'capacity_pages': 1}]
    level, child_capacity = 1, 1
    while len(current) > 1:
        parents = []
        level_pixels = 0
        for offset in range(0, len(current), FANOUT):
            children = current[offset:offset + FANOUT]
            total_pages = sum(child['pages'] for child in children)
            width, height = _layout(total_pages, screen_size)
            name = namespace + '_merge_l%02d_%05d' % (level, offset // FANOUT)
            values = {'node': [float(width), float(height), float(child_capacity), float(total_pages)],
                      'layout': [float(screen_size[1]), float(WORDS_PER_PAGE), 0.0, 0.0]}
            merge_parameters[name] = values
            processes.append({'name': name, 'enable': False,
                              'paras': [_parameter(parameter, values[parameter],
                                                    max(payload_bytes, child_capacity, *screen_size))
                                        for parameter in ('node', 'layout')],
                              'pass_array': [_pass(MERGE_MATERIAL, [width, height], screen_size)]})
            for index, child in enumerate(children):
                connections.append([child['name'], 0, name, 0, 3 + index])
            node = {'name': name, 'level': level, 'first_page': children[0]['first_page'],
                    'pages': total_pages, 'target_pixels': [width, height],
                    'child_capacity_pages': child_capacity,
                    'children': [child['name'] for child in children]}
            nodes.append(node)
            parents.append(node)
            producer_names.append(name)
            level_pixels += width * height
        levels.append({'level': level, 'nodes': len(parents), 'passes': len(parents),
                       'pixels': level_pixels, 'capacity_pages': child_capacity * FANOUT})
        current = parents
        level += 1
        child_capacity *= FANOUT

    root = current[0]['name']
    query = [0.0, 0.0, float(min(payload_bytes, 3072)), 7.0]
    display_layout = [float(root_width), float(root_height), float(payload_bytes), 0.0]
    processes.append({'name': display, 'enable': False, 'paras': [
        _parameter('query', query, max(payload_bytes, 3072)),
        _parameter('display_rect', DISPLAY_RECT, 1.0),
        _parameter('atlas_layout', display_layout, max(payload_bytes, *screen_size))],
        'pass_array': [_pass(CONSUMER_MATERIAL, screen_size, screen_size)]})
    connections.extend([[root, 0, display, 0, 3], [saved, 0, display, 0, 4]])
    data_pixels = sum(item['pixels'] for item in levels)
    full_screen_pixels = screen_size[0] * screen_size[1]
    stats = {'levels': levels, 'leaf_nodes': pages,
             'merge_nodes': len(merge_parameters), 'data_passes': len(producer_names),
             'total_passes': len(processes), 'data_pixels_per_frame': data_pixels,
             'save_consumer_pixels_per_frame': 2 * full_screen_pixels,
             'total_pixels_per_frame': data_pixels + 2 * full_screen_pixels,
             'flat_full_atlas_chain_pixels_per_frame': pages * root_width * root_height,
             'pixel_basis': 'requested targets; native allocation and performance unverified'}
    return {'transport': 'tree_atlas', 'namespace': namespace, 'pages': pages,
            'payload_bytes': payload_bytes, 'storage_bytes': pages * BYTES_PER_PAGE,
            'words_per_page': WORDS_PER_PAGE, 'bytes_per_page': BYTES_PER_PAGE,
            'parameter_names': list(PARAMETER_NAMES), 'packet_divisor': 16777216,
            'screen_size': screen_size, 'target_pixels': [root_width, root_height],
            'layout': {'columns': root_width, 'rows': root_height},
            'display_rect_norm': list(DISPLAY_RECT), 'query': query,
            'display_layout': display_layout, 'leaf_names': leaf_names,
            'producer_names': producer_names, 'merge_parameters': merge_parameters,
            'saved_scene_name': saved, 'display_name': display, 'root_name': root,
            'processes': processes, 'connections': connections, 'nodes': nodes,
            'stats': stats, 'levels': levels, 'fanout': FANOUT,
            'data_sampler': 3, 'scene_sampler': 4, 'byte_order': 'big_endian_rgb',
            'gpu_verified': False}


def _material(filename, samplers):
    return {'vertexShader': 'shaders/uv_fullscreen.vertex',
            'fragmentShader': 'shaders/' + filename,
            'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
            'samplerStates': [{'samplerIndex': index, 'textureWrap': 'Clamp',
                               'textureFilter': 'Point'} for index in samplers],
            'states': ['DisableDepthTest', 'DisableDepthWrite'], 'msaaSupport': 'Both'}


def build_tree_assets(resource_pack, **options):
    """Install new tree assets only in a marked, isolated packet-probe project."""
    resource = Path(resource_pack).resolve()
    marker = resource.parent / '.pmanim_packet_probe.json'
    if resource.name != 'resource_pack' or not marker.is_file():
        raise ValueError('tree assets require an owned isolated packet probe')
    if json.loads(marker.read_text(encoding='utf-8')).get('kind') != 'pmanim_runtime_packet_probe':
        raise ValueError('invalid packet probe ownership marker')
    runtime = resource.parent / 'behavior_pack/packet_probe'
    if not runtime.is_dir():
        raise ValueError('packet probe runtime is missing')
    filenames = ('tree_leaf.fragment', 'tree_merge.fragment', 'tree_consumer.fragment',
                 'isolated_copy.fragment')
    runtime_files = ('isolated_runtime.py', 'tree_runtime.py')
    for filename in filenames + runtime_files:
        if not (HERE / filename).is_file():
            raise ValueError('tree source asset is missing: ' + filename)
    config = tree_config(**options)
    path = resource / 'materials/postprocess.material'
    materials = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    additions = {LEAF_MATERIAL: _material('tree_leaf.fragment', ()),
                 MERGE_MATERIAL: _material('tree_merge.fragment', (3, 4, 5, 6, 7)),
                 SAVE_MATERIAL: _material('isolated_copy.fragment', (0,)),
                 CONSUMER_MATERIAL: _material('tree_consumer.fragment', (3, 4))}
    collisions = set(materials).intersection(additions)
    if any(materials[name] != additions[name] for name in collisions):
        raise ValueError('refusing to overwrite a different existing tree material')
    materials.update(additions)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(materials, indent=2) + '\n', encoding='utf-8')
    for filename in filenames:
        destination = resource / 'shaders/glsl' / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / filename, destination)
    for filename in runtime_files:
        shutil.copyfile(HERE / filename, runtime / filename)
    return config
