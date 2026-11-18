"""Pure Python2/3 layouts for the k2,24-byte/32-pixel large scene codec."""

SCREEN = (1080, 1440)
SOURCE_LEFT = 8
SOURCE_TOP = 128
SOURCE_COLUMNS = 704
BLOCK_PIXELS = 32
BLOCK_BYTES = 24
PAGE_RECORDS = 65536
MAX_BYTES = 524288
DIAGNOSTIC = (8, 128, 1024, 1)
GUARD = (0, 128, 1080, 1408)


def plan_payload(logical_bytes, bits=2):
    if bits != 2 or isinstance(logical_bytes, bool) or int(logical_bytes) != logical_bytes:
        raise ValueError('This large probe uses integer byte counts and RGB k2')
    logical = int(logical_bytes)
    if not 1 <= logical <= MAX_BYTES:
        raise ValueError('Logical payload must be1..524288bytes')
    required_blocks = (logical + BLOCK_BYTES - 1) // BLOCK_BYTES
    blocks_per_row = SOURCE_COLUMNS // BLOCK_PIXELS
    rows = (required_blocks + blocks_per_row - 1) // blocks_per_row
    records = SOURCE_COLUMNS * rows
    allocated = records * 3 // 4
    if SOURCE_TOP + rows > GUARD[3]:
        raise ValueError('Source exceeds the declared safe native region')
    pages = []
    for ordinal, base in enumerate(range(0, records, PAGE_RECORDS)):
        count = min(PAGE_RECORDS, records-base)
        stride = 2
        while stride*stride < count:
            stride *= 2
        pages.append({'page': ordinal, 'record_base': base, 'record_count': count,
            'payload_byte_base': base*3//4, 'payload_byte_count': count*3//4,
            'stride': stride, 'palette_height': 16, 'palette_volume': stride*stride*16})
    return {'rgb_bits': 2, 'logical_bytes': logical, 'block_bytes': BLOCK_BYTES,
        'block_pixels': BLOCK_PIXELS, 'block_aligned_bytes': required_blocks*BLOCK_BYTES,
        'allocated_bytes': allocated, 'padding_bytes': allocated-logical,
        'required_blocks': required_blocks, 'allocated_blocks': records//BLOCK_PIXELS,
        'records': records, 'roi': [SOURCE_LEFT,SOURCE_TOP,SOURCE_COLUMNS,rows],
        'screen_size': list(SCREEN), 'diagnostic_layout': list(DIAGNOSTIC),
        'guard_rect_native': list(GUARD), 'page_record_budget': PAGE_RECORDS, 'pages': pages,
        'declared_palette_volume_sum': sum(page['palette_volume'] for page in pages)}


def expected_byte(seed, generation, index):
    mask = 0xffffffff
    value = (int(seed) ^ ((int(generation)*0x9e3779b9)&mask) ^ ((int(index)*0x85ebca6b)&mask))&mask
    value ^= value >> 16
    value = (value*0x7feb352d)&mask
    value ^= value >> 15
    value = (value*0x846ca68b)&mask
    return (value ^ (value >> 16))&255


def page_payload(plan, page_index, seed=54321, generation=1):
    page = plan['pages'][int(page_index)]
    start, count = page['payload_byte_base'], page['payload_byte_count']
    logical = plan['logical_bytes']
    return bytearray(expected_byte(seed,generation,index) if index < logical else 0
        for index in range(start,start+count))


def lookup_address(index, logical_bytes, mode, seed=54321, generation=1):
    if mode not in (0,1,2) or not 0 <= index < logical_bytes:
        raise ValueError('Query mode or logical index out of range')
    address = int(index)
    if mode:
        address = (131*address+29)%logical_bytes
    if mode == 2:
        address = (address+257*expected_byte(seed,generation,address)+113)%logical_bytes
    return address
