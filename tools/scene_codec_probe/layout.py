"""Pure host/game layout planning for the finite native scene codec fixture."""


def plan_payload(byte_count, bits):
    if bits not in (1, 2) or int(byte_count) != byte_count or byte_count < 1:
        raise ValueError('Use a positive byte count and k=1/2')
    logical = int(byte_count)
    block_bytes = 12 * bits
    blocks = (logical + block_bytes - 1) // block_bytes
    # One block is 32 adjacent pixels. Keep every row block aligned and fit
    # x=8..711, y=32..1055 in the fixed 720x1080 native render target.
    candidates = [(width * ((blocks + width - 1) // width), width,
                   (blocks + width - 1) // width) for width in range(1, 23)
                  if (blocks + width - 1) // width <= 1024]
    if not candidates:
        raise ValueError('Payload exceeds the finite 704x1024 scene ROI')
    allocated_blocks, blocks_per_row, rows = min(candidates)
    return {'logical_bytes': logical, 'block_aligned_bytes': blocks * block_bytes,
            'allocated_bytes': allocated_blocks * block_bytes,
            'padding_bytes': allocated_blocks * block_bytes - logical,
            'columns': blocks_per_row * 32, 'rows': rows,
            'pixels': allocated_blocks * 32, 'blocks': allocated_blocks,
            'roi': [8, 32, blocks_per_row * 32, rows]}
