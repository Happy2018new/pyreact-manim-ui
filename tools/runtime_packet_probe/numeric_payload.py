# -*- coding: utf-8 -*-
"""Pure Python 2/3 float32 packets; no SDK calls, files, or GPU work.

Each scalar uses IEEE754 little-endian float32 bytes. Consecutive groups of
three bytes become a uint24 word in high/middle/low byte order; eight words
make one page. ``pages`` is the minimum number of pages for the real data.
Page-tail zero bytes are explicit ``padding_bytes``, never scalar data.
Numeric conversion follows struct.pack('<f'), including Python int/long's
intermediate conversion to double; it does not promise exact large integers.

``encode(values, capacity_pages)`` returns the header fields, ``words`` rows,
float32-rounded ``values``, and unpadded binary ``wire_bytes``. The latter is a
Python 2 str / Python 3 bytes, so exclude it when serializing a JSON receipt.
``decode(packet)`` reads the words and header, and checks the optional values
and wire_bytes copies when present. It also accepts a header/words-only dict.
"""
import math
import struct


WORDS_PER_PAGE = 8
BYTES_PER_WORD = 3
BYTES_PER_PAGE = WORDS_PER_PAGE * BYTES_PER_WORD
BYTES_PER_SCALAR = 4
UINT24_LIMIT = 1 << 24
# type(1 << 64) includes Python 2 long without importing a compatibility module.
INTEGER_TYPES = (int, type(1 << 64))
NUMBER_TYPES = INTEGER_TYPES + (float,)
BINARY_TYPE = type(b"")
UINT32 = struct.Struct(">I")
# At this rounding boundary float32 becomes infinity. Values slightly above
# its maximum finite value may still round down to that finite float32 value.
FLOAT32_OVERFLOW = 2.0 ** 128 - 2.0 ** 103


def _integer(value, name):
    if isinstance(value, bool) or not isinstance(value, INTEGER_TYPES) or value < 0:
        raise ValueError("%s must be a nonnegative integer" % name)
    return value


def _validate_values(values):
    if not isinstance(values, (list, tuple)):
        raise ValueError("values must be a flat list or tuple of finite numbers")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, NUMBER_TYPES):
            raise ValueError("values must contain only finite Python float/int scalars")
        # Check the range before math converts an arbitrarily large Python int.
        if value <= -FLOAT32_OVERFLOW or value >= FLOAT32_OVERFLOW:
            raise ValueError("values overflow finite float32")
        numeric = float(value)
        # struct converts Python int/long through double before float32. A huge
        # integer just below the cutoff can round up during that conversion.
        if numeric <= -FLOAT32_OVERFLOW or numeric >= FLOAT32_OVERFLOW:
            raise ValueError("values overflow finite float32")
        if math.isnan(numeric) or math.isinf(numeric):
            raise ValueError("values must be finite")


def _unpack_values(wire_bytes, scalar_count):
    if not scalar_count:
        return []
    values = list(struct.unpack("<%df" % scalar_count, wire_bytes))
    if any(math.isnan(value) or math.isinf(value) for value in values):
        raise ValueError("word payload must contain only finite float32 values")
    return values


def encode(values, capacity_pages):
    """Validate a complete flat payload, then encode it without truncation.

    Capacity is measured in 24-byte pages (six float32 scalars per page).
    Empty input needs zero pages and works with zero capacity. The input and
    all of its values are validated before building any packet or wire data.
    """
    capacity_pages = _integer(capacity_pages, "capacity_pages")
    _validate_values(values)
    scalar_count = len(values)
    byte_count = scalar_count * BYTES_PER_SCALAR
    pages = (byte_count + BYTES_PER_PAGE - 1) // BYTES_PER_PAGE
    if pages > capacity_pages:
        raise ValueError("payload exceeds capacity_pages; no values were truncated")
    padding_bytes = pages * BYTES_PER_PAGE - byte_count
    wire_bytes = struct.pack("<%df" % scalar_count, *values) if scalar_count else b""
    rounded_values = _unpack_values(wire_bytes, scalar_count)
    octets = bytearray(wire_bytes + b"\x00" * padding_bytes)
    flat_words = [(octets[offset] << 16) | (octets[offset + 1] << 8) | octets[offset + 2]
                  for offset in range(0, len(octets), BYTES_PER_WORD)]
    words = [flat_words[offset:offset + WORDS_PER_PAGE]
             for offset in range(0, len(flat_words), WORDS_PER_PAGE)]
    return {"scalar_count": scalar_count, "byte_count": byte_count,
            "words_per_page": WORDS_PER_PAGE, "pages": pages,
            "padding_bytes": padding_bytes, "words": words,
            "values": rounded_values, "wire_bytes": wire_bytes}


def decode(packet):
    """Reconstruct finite float32 scalars from a strict header and word pages.

    All header/row/word lengths are checked before allocating the wire buffer.
    Extra pages, nonzero padding, nonfinite floats, and inconsistent optional
    values/wire_bytes copies are errors. Padding is never returned as values.
    """
    if not isinstance(packet, dict):
        raise ValueError("packet must be a dict")
    scalar_count = _integer(packet.get("scalar_count"), "scalar_count")
    byte_count = _integer(packet.get("byte_count"), "byte_count")
    pages = _integer(packet.get("pages"), "pages")
    words_per_page = _integer(packet.get("words_per_page"), "words_per_page")
    padding_bytes = _integer(packet.get("padding_bytes"), "padding_bytes")
    if words_per_page != WORDS_PER_PAGE:
        raise ValueError("words_per_page must be 8")
    if byte_count != scalar_count * BYTES_PER_SCALAR:
        raise ValueError("byte_count must equal scalar_count * 4")
    if pages != (byte_count + BYTES_PER_PAGE - 1) // BYTES_PER_PAGE:
        raise ValueError("pages must be the minimum page count for byte_count")
    if padding_bytes != pages * BYTES_PER_PAGE - byte_count:
        raise ValueError("padding_bytes does not match the declared data length")
    words = packet.get("words")
    if not isinstance(words, (list, tuple)) or len(words) != pages:
        raise ValueError("words must contain exactly the declared pages")
    for page in words:
        if not isinstance(page, (list, tuple)) or len(page) != WORDS_PER_PAGE:
            raise ValueError("each page must contain exactly 8 uint24 words")
        for word in page:
            if (isinstance(word, bool) or not isinstance(word, INTEGER_TYPES) or
                    not 0 <= word < UINT24_LIMIT):
                raise ValueError("page words must be uint24 integers")
    padded_bytes = b"".join(UINT32.pack(word)[1:] for page in words for word in page)
    if padded_bytes[byte_count:] != b"\x00" * padding_bytes:
        raise ValueError("padding bytes must all be zero")
    wire_bytes = padded_bytes[:byte_count]
    values = _unpack_values(wire_bytes, scalar_count)
    if "wire_bytes" in packet:
        provided_bytes = packet["wire_bytes"]
        if not isinstance(provided_bytes, BINARY_TYPE) or provided_bytes != wire_bytes:
            raise ValueError("wire_bytes does not match the word payload")
    if "values" in packet:
        provided_values = packet["values"]
        _validate_values(provided_values)
        if len(provided_values) != scalar_count:
            raise ValueError("values length does not match scalar_count")
        provided_bytes = (struct.pack("<%df" % scalar_count, *provided_values)
                          if scalar_count else b"")
        if provided_bytes != wire_bytes:
            raise ValueError("values do not match the word payload")
    return values
