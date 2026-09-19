"""Pure-Python OSM PBF bbox extractor (no pyosmium / osmium binary needed).

Reads an .osm.pbf (e.g. a Geofabrik regional extract), keeps the elements
inside a bounding box, and writes a small .osm XML file that osmnx's
graph_from_xml / features_from_xml can parse.

Usage:
  python -m src.osmpbf_extract INPUT.pbf OUTPUT.osm --core "min_lat,min_lon,max_lat,max_lon"
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

_WAY_HOSPITAL = {"amenity": "hospital", "healthcare": "hospital", "building": "hospital"}

_DRIVE_HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential",
    "service", "living_street",
}


def _read_varint(buf: bytes, off: int) -> tuple[int, int]:
    shift = 0
    val = 0
    while True:
        b = buf[off]
        off += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, off
        shift += 7


def _zigzag(v: int) -> int:
    return (v >> 1) ^ -(v & 1)


def _packed_sint64(data: bytes):
    off = 0
    while off < len(data):
        v, off = _read_varint(data, off)
        yield _zigzag(v)


def _packed_u32(data: bytes):
    off = 0
    while off < len(data):
        v, off = _read_varint(data, off)
        yield v


def _skip(buf: bytes, off: int, wt: int) -> int:
    if wt == 0:
        _, off = _read_varint(buf, off)
    elif wt == 1:
        off += 8
    elif wt == 2:
        n, off = _read_varint(buf, off)
        off += n
    elif wt == 5:
        off += 4
    else:
        raise ValueError(f"unsupported wire type {wt}")
    return off


class _Msg:
    """Tiny protobuf message: list of (field_num, wire_type, value)."""

    __slots__ = ("fields",)

    def __init__(self, buf: bytes):
        self.fields = []
        off = 0
        while off < len(buf):
            tag, off = _read_varint(buf, off)
            num, wt = tag >> 3, tag & 7
            if wt == 2:
                _v, off = _read_varint(buf, off)
                self.fields.append((num, wt, bytes(buf[off : off + _v])))
                off += _v
            elif wt in (0, 1, 5):
                start = off
                off = _skip(buf, off, wt)
                self.fields.append((num, wt, (buf, start)))
            else:
                off = _skip(buf, off, wt)


def _vint(field) -> int:
    num, wt, val = field
    if wt != 0:
        return 0
    b, off = val
    return _read_varint(b, off)[0]


def _sint(field) -> int:
    num, wt, val = field
    if wt != 0:
        return 0
    b, off = val
    return _zigzag(_read_varint(b, off)[0])


def _packed(field) -> list[int]:
    num, wt, val = field
    if wt != 2:
        return []
    return list(_packed_sint64(val))


def _packed_keys(field) -> list[int]:
    num, wt, val = field
    if wt != 2:
        return []
    return list(_packed_u32(val))


def _submsg(field):
    num, wt, val = field
    return _Msg(val) if wt == 2 else None


class _Blob:
    def __init__(self, buf: bytes):
        msg = _Msg(buf)
        raw = next((f[2] for f in msg.fields if f[0] == 1), None)
        zdata = next((f[2] for f in msg.fields if f[0] == 3), None)
        self.data = raw if raw is not None else zlib.decompress(zdata)


class _Header:
    def __init__(self, buf: bytes):
        msg = _Msg(buf)
        self.type = next((f[2] for f in msg.fields if f[0] == 1), b"").decode()
        self.datasize = next((_vint(f) for f in msg.fields if f[0] == 3), 0)


def _read_blob(f) -> tuple[str, bytes]:
    hdr = f.read(4)
    if not hdr:
        return "", b""
    hdr_len = struct.unpack(">I", hdr)[0]
    header = _Header(f.read(hdr_len))
    data = _Blob(f.read(header.datasize)).data
    return header.type, data


class _Block:
    def __init__(self, buf: bytes):
        msg = _Msg(buf)
        self.strings: list[str] = []
        for f in msg.fields:
            if f[0] == 1:
                st = _submsg(f)
                if st:
                    for s in st.fields:
                        if s[0] == 1:
                            self.strings.append(s[2].decode("utf-8", errors="replace"))
        self.granularity = next((_vint(f) for f in msg.fields if f[0] == 17), 100)
        self.lat_offset = next((_vint(f) for f in msg.fields if f[0] == 19), 0)
        self.lon_offset = next((_vint(f) for f in msg.fields if f[0] == 20), 0)
        self.groups = [_submsg(f) for f in msg.fields if f[0] == 2]

    def scan_nodes(self, in_buf):
        for grp in self.groups:
            for gf in grp.fields:
                if gf[0] == 1:  # Node
                    n = _submsg(gf)
                    nid = None
                    for f in n.fields:
                        if f[0] == 1:
                            nid = _sint(f)
                        elif f[0] == 8:
                            nlat = _sint(f)
                        elif f[0] == 9:
                            nlon = _sint(f)
                    if nid is None:
                        continue
                    lat = (self.lat_offset + nlat * self.granularity) * 1e-9
                    lon = (self.lon_offset + nlon * self.granularity) * 1e-9
                    if not in_buf(lon, lat):
                        continue
                    keys = _packed_keys(next((f for f in n.fields if f[0] == 2), (0, 0, b"")))
                    vals = _packed_keys(next((f for f in n.fields if f[0] == 3), (0, 0, b"")))
                    tags = {self.strings[k]: self.strings[v]
                            for k, v in zip(keys, vals) if k < len(self.strings)}
                    yield (nid, lat, lon, tags)
                elif gf[0] == 2:  # DenseNodes
                    d = _submsg(gf)
                    ids, lats, lons, kv = [], [], [], []
                    for f in d.fields:
                        if f[0] == 1:
                            ids = _packed(f)
                        elif f[0] == 8:
                            lats = _packed(f)
                        elif f[0] == 9:
                            lons = _packed(f)
                        elif f[0] == 10:
                            kv = _packed(f)
                    nid = lat = lon = 0
                    ti = 0
                    for i in range(len(ids)):
                        nid += ids[i]
                        lat += lats[i]
                        lon += lons[i]
                        tags = {}
                        while ti + 1 < len(kv) and kv[ti] != 0:
                            tags[self.strings[kv[ti]]] = self.strings[kv[ti + 1]]
                            ti += 2
                        if ti < len(kv) and kv[ti] == 0:
                            ti += 1
                        y = (self.lat_offset + lat * self.granularity) * 1e-9
                        x = (self.lon_offset + lon * self.granularity) * 1e-9
                        if in_buf(x, y):
                            yield (nid, y, x, tags)

    def scan_ways(self):
        for grp in self.groups:
            for gf in grp.fields:
                if gf[0] != 3:  # Way (field 4 in PrimitiveGroup is Relation)
                    continue
                w = _submsg(gf)
                wid = next((_vint(f) for f in w.fields if f[0] == 1), None)
                if wid is None:
                    continue
                keys = _packed_keys(next((f for f in w.fields if f[0] == 2), (0, 0, b"")))
                vals = _packed_keys(next((f for f in w.fields if f[0] == 3), (0, 0, b"")))
                tags = {self.strings[k]: self.strings[v]
                        for k, v in zip(keys, vals) if k < len(self.strings)}
                refs = []
                acc = 0
                for r in _packed(next((f for f in w.fields if f[0] == 8), (0, 0, b""))):
                    acc += r
                    refs.append(acc)
                yield (wid, tags, refs)


def extract(pbf_path: Path, out_path: Path,
            core: tuple[float, float, float, float],
            margin_deg: float = 0.025) -> dict:
    """core = (min_lat, min_lon, max_lat, max_lon). Returns stats dict."""
    min_lat, min_lon, max_lat, max_lon = core
    b_min_lat, b_min_lon = min_lat - margin_deg, min_lon - margin_deg
    b_max_lat, b_max_lon = max_lat + margin_deg, max_lon + margin_deg

    def in_buf(lon, lat):
        return b_min_lon <= lon <= b_max_lon and b_min_lat <= lat <= b_max_lat

    def in_core(lon, lat):
        return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat

    stats = {"nodes_in_buffer": 0, "nodes_in_core": 0, "ways_kept": 0}

    node_pos: dict[int, tuple[float, float]] = {}
    node_tags: dict[int, dict] = {}
    ways: dict[int, dict] = {}

    with pbf_path.open("rb") as f:
        _read_blob(f)  # skip file header
        while True:
            typ, data = _read_blob(f)
            if not data:
                break
            if typ != "OSMData":
                continue
            block = _Block(data)
            for nid, lat, lon, tags in block.scan_nodes(in_buf):
                node_pos[nid] = (lat, lon)
                if tags:
                    node_tags[nid] = tags
                stats["nodes_in_buffer"] += 1
                if in_core(lon, lat):
                    stats["nodes_in_core"] += 1
            for wid, tags, refs in block.scan_ways():
                drive = "highway" in tags and tags["highway"] in _DRIVE_HIGHWAYS
                hospital = any(tags.get(k) == v for k, v in _WAY_HOSPITAL.items())
                if drive or hospital:
                    ways[wid] = {"tags": tags, "refs": refs}
            del block

    kept: dict[int, dict] = {}
    refs_needed: set[int] = set()
    for wid, w in ways.items():
        refs = [r for r in w["refs"] if r in node_pos]
        touches_core = sum(1 for r in refs if in_core(node_pos[r][1], node_pos[r][0])) >= 1
        if touches_core:
            kept[wid] = w
            refs_needed.update(refs)
            stats["ways_kept"] += 1
        elif "highway" not in w["tags"] and any(
            w["tags"].get(k) == v for k, v in _WAY_HOSPITAL.items()
        ) and len(refs) > 0:
            kept[wid] = w
            refs_needed.update(refs)
            stats["ways_kept"] += 1

    with pbf_path.open("rb") as f, out_path.open("w", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6">\n')
        _read_blob(f)
        while True:
            typ, data = _read_blob(f)
            if not data:
                break
            if typ != "OSMData":
                continue
            block = _Block(data)
            for nid, lat, lon, tags in block.scan_nodes(in_buf):
                if nid not in refs_needed:
                    continue
                tags = node_tags.get(nid, tags)
                out.write(f'  <node id="{nid}" lat="{lat:.7f}" lon="{lon:.7f}">')
                for k, v in tags.items():
                    out.write(f'<tag k="{_esc(k)}" v="{_esc(v)}"/>')
                out.write("</node>\n")
            for wid, tags, refs in block.scan_ways():
                if wid not in kept:
                    continue
                out.write(f'  <way id="{wid}">')
                for r in kept[wid]["refs"]:
                    if r in refs_needed:
                        out.write(f'<nd ref="{r}"/>')
                for k, v in kept[wid]["tags"].items():
                    out.write(f'<tag k="{_esc(k)}" v="{_esc(v)}"/>')
                out.write("</way>\n")
            del block
        out.write("</osm>\n")

    return stats


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pbf")
    ap.add_argument("out")
    ap.add_argument("--core", required=True,
                    help="min_lat,min_lon,max_lat,max_lon")
    ap.add_argument("--margin", type=float, default=0.025)
    args = ap.parse_args()
    core = tuple(float(x) for x in args.core.split(","))
    stats = extract(Path(args.pbf), Path(args.out), core, margin_deg=args.margin)
    size = Path(args.out).stat().st_size
    print(f"OK wrote {args.out} ({size:,} bytes). Stats: {stats}")


if __name__ == "__main__":
    sys.exit(main())