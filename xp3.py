import argparse
import hashlib
import io
import mmap
import os
import struct
import sys
import zlib
from pathlib import Path
from typing import Any, Dict, List

XP3_SIGNATURE = b'XP3\r\n \n\x1a\x8b\x67\x01'
KRKR_230_MAGIC = b'\x17\x00\x00\x00\x00\x00\x00\x00'
KRKR_230_HEADER_PART2 = b'\x01\x00\x00\x00\x80' + b'\x00' * 8
CHUNK_FILE = b'File'
CHUNK_INFO = b'info'
CHUNK_SEGM = b'segm'
CHUNK_ADLR = b'adlr'

UINT64_LE = struct.Struct('<Q')
UINT32_LE = struct.Struct('<I')
UINT16_LE = struct.Struct('<H')

SEGMENT_RECORD_SIZE = 4 + 8 * 3


class BufferReader:
    __slots__ = ("data", "pos", "_len")

    def __init__(self, data: bytes | bytearray | mmap.mmap):
        self.data = data
        self._len = len(data)
        self.pos = 0

    def read(self, size: int) -> bytes:
        if size < 0:
            raise ValueError("size must be non-negative.")
        end = self.pos + size
        if end > self._len:
            raise EOFError("Attempted to read past the end of the buffer.")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def skip(self, size: int) -> None:
        if size < 0:
            raise ValueError("size must be non-negative.")
        end = self.pos + size
        if end > self._len:
            raise EOFError("Attempted to skip past the end of the buffer.")
        self.pos = end

    def read_u16(self) -> int:
        return UINT16_LE.unpack(self.read(2))[0]

    def read_u32(self) -> int:
        return UINT32_LE.unpack(self.read(4))[0]

    def read_u64(self) -> int:
        return UINT64_LE.unpack(self.read(8))[0]

    def peek(self, size: int) -> bytes:
        end = self.pos + size
        if end > self._len:
            end = self._len
        return self.data[self.pos:end]

    def remaining_data(self) -> bytes:
        return self.data[self.pos:self._len]

    @property
    def eof(self) -> bool:
        return self.pos >= self._len

    @property
    def remaining(self) -> int:
        return self._len - self.pos


class XP3Parser:
    def __init__(self, xp3_path: str | Path):
        self.xp3_path = Path(xp3_path)
        if not self.xp3_path.is_file():
            raise FileNotFoundError(f"XP3 file not found: {self.xp3_path}")
        self.xp3_file: mmap.mmap | None = None
        self.xp3_data: mmap.mmap | None = None
        self.file_manager: List[Dict[str, Any]] = []

    def __enter__(self) -> "XP3Parser":
        self.xp3_file = open(self.xp3_path, 'rb')
        try:
            self.xp3_data = mmap.mmap(self.xp3_file.fileno(), 0, access=mmap.ACCESS_READ)
            self._parse()
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        if self.xp3_data is not None:
            self.xp3_data.close()
            self.xp3_data = None
        if self.xp3_file is not None:
            self.xp3_file.close()
            self.xp3_file = None

    def _parse(self) -> None:
        assert self.xp3_data is not None
        header_offset = self.xp3_data.find(XP3_SIGNATURE)
        if header_offset == -1:
            raise ValueError("Invalid XP3 header signature.")
        reader = BufferReader(self.xp3_data)
        reader.pos = header_offset
        file_manager_offset = self._parse_xp3_header(reader)
        self.file_manager = self._parse_file_manager(file_manager_offset)

    def _parse_xp3_header(self, reader: BufferReader) -> int:
        reader.read(len(XP3_SIGNATURE))
        if reader.peek(len(KRKR_230_MAGIC)) == KRKR_230_MAGIC:
            reader.skip(len(KRKR_230_MAGIC) + len(KRKR_230_HEADER_PART2))
        return reader.read_u64()

    def _parse_file_manager(self, offset: int) -> List[Dict[str, Any]]:
        assert self.xp3_data is not None
        reader = BufferReader(self.xp3_data)
        reader.pos = offset
        is_compressed = reader.read(1)[0]
        if is_compressed:
            compressed_size = reader.read_u64()
            uncompressed_size = reader.read_u64()
            compressed_data = reader.read(compressed_size)
            index_data = zlib.decompress(compressed_data)
            if len(index_data) != uncompressed_size:
                raise ValueError("Decompressed file manager size mismatch.")
        else:
            uncompressed_size = reader.read_u64()
            index_data = reader.read(uncompressed_size)
        return self._parse_file_entries(BufferReader(index_data))

    def _parse_file_entries(self, reader: BufferReader) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        read = reader.read
        read_u64 = reader.read_u64
        chunk_file = CHUNK_FILE
        while not reader.eof:
            if reader.remaining < 12:
                break
            chunk_id = read(4)
            if chunk_id != chunk_file:
                break
            entry_size = read_u64()
            if entry_size > reader.remaining:
                raise ValueError("File entry size exceeds remaining index data.")
            entry_reader = BufferReader(read(entry_size))
            entry: Dict[str, Any] = {}
            while not entry_reader.eof:
                if entry_reader.remaining < 12:
                    break
                sub_chunk_id = entry_reader.read(4)
                sub_chunk_size = entry_reader.read_u64()
                if sub_chunk_size > entry_reader.remaining:
                    raise ValueError("Sub-chunk size exceeds remaining entry data.")
                chunk_data_reader = BufferReader(entry_reader.read(sub_chunk_size))
                if sub_chunk_id == CHUNK_INFO:
                    entry['info'] = self._parse_info_chunk(chunk_data_reader)
                elif sub_chunk_id == CHUNK_SEGM:
                    entry['segm'] = self._parse_segm_chunk(chunk_data_reader)
                elif sub_chunk_id == CHUNK_ADLR:
                    entry['adlr'] = self._parse_adlr_chunk(chunk_data_reader)
                else:
                    break
            entries.append(entry)
        return entries

    @staticmethod
    def _parse_info_chunk(reader: BufferReader) -> Dict[str, Any]:
        flags = reader.read_u32()
        uncompressed_size = reader.read_u64()
        storage_size = reader.read_u64()
        file_name_len_chars = reader.read_u16()
        name_bytes_len = file_name_len_chars * 2
        if name_bytes_len > reader.remaining:
            name_bytes_len = reader.remaining
        file_name_bytes = reader.read(name_bytes_len)
        info: Dict[str, Any] = {
            "protect_flag": (flags & (1 << 31)) != 0,
            "uncompressed_size": uncompressed_size,
            "storage_size": storage_size,
            "file_name_len_chars": file_name_len_chars,
        }
        try:
            info["file_name"] = file_name_bytes.decode('utf-16-le').rstrip('\x00')
        except UnicodeDecodeError:
            info["file_name"] = hashlib.md5(file_name_bytes).hexdigest()
        return info

    @staticmethod
    def _parse_segm_chunk(reader: BufferReader) -> List[Dict[str, Any]]:
        segments: List[Dict[str, Any]] = []
        read_u32 = reader.read_u32
        read_u64 = reader.read_u64
        while reader.remaining >= SEGMENT_RECORD_SIZE:
            flags = read_u32()
            segment = {
                "compressed_flag": bool(flags),
                "offset": read_u64(),
                "uncompressed_size": read_u64(),
                "storage_size": read_u64(),
            }
            segments.append(segment)
        return segments

    @staticmethod
    def _parse_adlr_chunk(reader: BufferReader) -> int:
        return reader.read_u32()

    def extract(self, output_dir: str | Path | None = None) -> None:
        if self.xp3_data is None:
            raise RuntimeError(
                "XP3Parser is not initialized. Use it as a context manager or call __enter__ manually."
            )
        if output_dir is None:
            output_dir = self.xp3_path.with_name(f"{self.xp3_path.stem}_extracted")
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        xp3_data = self.xp3_data
        for file_entry in self.file_manager:
            info = file_entry.get("info") or {}
            segments = file_entry.get("segm") or []
            if not info or not segments:
                continue
            file_name = info.get("file_name", "unnamed_file")
            try:
                relative_path = Path(file_name.replace('/', os.sep))
                output_path = output_dir / relative_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                output_path = output_dir / hashlib.md5(
                    file_name.encode('utf-8', errors='replace')
                ).hexdigest()
            with open(output_path, 'wb') as f_out:
                for segment in segments:
                    offset = segment["offset"]
                    storage_size = segment["storage_size"]
                    compressed_flag = segment["compressed_flag"]
                    seg_data = xp3_data[offset: offset + storage_size]
                    if compressed_flag:
                        seg_data = zlib.decompress(seg_data)
                    f_out.write(seg_data)
        print(f"Extraction complete. Files saved to: {output_dir.resolve()}")


class XP3Packer:
    def __init__(
            self,
            input_dir: str | Path,
            output_xp3_path: str | Path,
            compress_level: int = 6,
    ):
        self.input_dir = Path(input_dir).resolve()
        self.output_xp3_path = Path(output_xp3_path).resolve()
        if not self.input_dir.is_dir():
            raise NotADirectoryError(f"Input directory not found: {self.input_dir}")
        if not (0 <= compress_level <= 9):
            raise ValueError("compress_level must be between 0 and 9.")
        self.compress_level = compress_level

    def pack(self) -> None:
        print(f"Starting to pack directory '{self.input_dir}' into '{self.output_xp3_path}'...")
        self.output_xp3_path.parent.mkdir(parents=True, exist_ok=True)
        file_metadata: List[Dict[str, Any]] = []
        with open(self.output_xp3_path, 'wb') as f_out:
            self._write_placeholder_header(f_out)
            files_to_pack = sorted(p for p in self.input_dir.rglob('*') if p.is_file())
            print(f"Found {len(files_to_pack)} files to pack.")
            compress_level = self.compress_level
            adler32 = zlib.adler32
            for file_path in files_to_pack:
                relative_path_str = file_path.relative_to(self.input_dir).as_posix()
                print(f"  - Processing: {relative_path_str}")
                uncompressed_data = file_path.read_bytes()
                uncompressed_size = len(uncompressed_data)
                is_compressed = compress_level > 0 and uncompressed_size > 0
                if is_compressed:
                    stored_data = zlib.compress(uncompressed_data, compress_level)
                else:
                    stored_data = uncompressed_data
                storage_size = len(stored_data)
                offset = f_out.tell()
                f_out.write(stored_data)
                metadata = {
                    "file_name": relative_path_str,
                    "offset": offset,
                    "uncompressed_size": uncompressed_size,
                    "storage_size": storage_size,
                    "is_compressed": is_compressed,
                    "adler32": adler32(uncompressed_data),
                }
                file_metadata.append(metadata)
            file_manager_offset = f_out.tell()
            raw_index_data = self._build_raw_index(file_metadata)
            compressed_index_data = zlib.compress(raw_index_data, compress_level)
            f_out.write(b'\x01')
            f_out.write(UINT64_LE.pack(len(compressed_index_data)))
            f_out.write(UINT64_LE.pack(len(raw_index_data)))
            f_out.write(compressed_index_data)
            f_out.seek(len(XP3_SIGNATURE) + len(KRKR_230_MAGIC) + len(KRKR_230_HEADER_PART2))
            f_out.write(UINT64_LE.pack(file_manager_offset))
        print(f"\nPacking complete. XP3 file saved to: {self.output_xp3_path}")

    @staticmethod
    def _write_placeholder_header(f) -> None:
        f.write(XP3_SIGNATURE)
        f.write(KRKR_230_MAGIC)
        f.write(KRKR_230_HEADER_PART2)
        f.write(UINT64_LE.pack(0))

    def _build_raw_index(self, all_metadata: List[Dict[str, Any]]) -> bytes:
        with io.BytesIO() as index_stream:
            write = index_stream.write
            pack_u64 = UINT64_LE.pack
            for meta in all_metadata:
                info_chunk = self._build_info_chunk(meta)
                segm_chunk = self._build_segm_chunk(meta)
                adlr_chunk = self._build_adlr_chunk(meta)
                file_chunk_size = len(info_chunk) + len(segm_chunk) + len(adlr_chunk)
                write(CHUNK_FILE)
                write(pack_u64(file_chunk_size))
                write(info_chunk)
                write(segm_chunk)
                write(adlr_chunk)
            return index_stream.getvalue()

    @staticmethod
    def _build_info_chunk(meta: Dict[str, Any]) -> bytes:
        file_name: str = meta['file_name']
        file_name_bytes = file_name.encode('utf-16-le')
        info_size = 4 + 8 + 8 + 2 + len(file_name_bytes)
        with io.BytesIO() as chunk:
            write = chunk.write
            write(CHUNK_INFO)
            write(UINT64_LE.pack(info_size))
            write(UINT32_LE.pack(0))
            write(UINT64_LE.pack(meta['uncompressed_size']))
            write(UINT64_LE.pack(meta['storage_size']))
            write(UINT16_LE.pack(len(file_name)))
            write(file_name_bytes)
            return chunk.getvalue()

    @staticmethod
    def _build_segm_chunk(meta: Dict[str, Any]) -> bytes:
        segm_size = SEGMENT_RECORD_SIZE
        with io.BytesIO() as chunk:
            write = chunk.write
            write(CHUNK_SEGM)
            write(UINT64_LE.pack(segm_size))
            write(UINT32_LE.pack(1 if meta['is_compressed'] else 0))
            write(UINT64_LE.pack(meta['offset']))
            write(UINT64_LE.pack(meta['uncompressed_size']))
            write(UINT64_LE.pack(meta['storage_size']))
            return chunk.getvalue()

    @staticmethod
    def _build_adlr_chunk(meta: Dict[str, Any]) -> bytes:
        adlr_size = 4
        with io.BytesIO() as chunk:
            write = chunk.write
            write(CHUNK_ADLR)
            write(UINT64_LE.pack(adlr_size))
            write(UINT32_LE.pack(meta['adler32']))
            return chunk.getvalue()


def cmd_extract(args: argparse.Namespace) -> int:
    try:
        with XP3Parser(args.xp3_path) as parser:
            parser.extract(args.output_dir)
        return 0
    except Exception as e:
        print(f"[extract] Error: {e}", file=sys.stderr)
        return 1


def cmd_pack(args: argparse.Namespace) -> int:
    try:
        packer = XP3Packer(
            input_dir=args.input_dir,
            output_xp3_path=args.output_xp3_path,
            compress_level=args.compress_level,
        )
        packer.pack()
        return 0
    except Exception as e:
        print(f"[pack] Error: {e}", file=sys.stderr)
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    try:
        with XP3Parser(args.xp3_path) as parser:
            if not parser.file_manager:
                print("No files found in XP3 archive.")
                return 0
            for i, entry in enumerate(parser.file_manager, start=1):
                info = entry.get("info") or {}
                name = info.get("file_name", "<unknown>")
                size = info.get("uncompressed_size", 0)
                storage = info.get("storage_size", 0)
                print(f"{i:4d}: {name}  ({size} bytes, stored: {storage} bytes)")
        return 0
    except Exception as e:
        print(f"[list] Error: {e}", file=sys.stderr)
        return 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xp3tool",
        description="XP3 packer / extractor",
    )
    subparsers = parser.add_subparsers(
        title="subcommands",
        dest="command",
        required=True,
    )
    p_extract = subparsers.add_parser(
        "extract",
        help="Extract files from an XP3 archive",
        description="Extract files from an XP3 archive into a directory.",
    )
    p_extract.add_argument(
        "xp3_path",
        help="Path to the XP3 archive",
    )
    p_extract.add_argument(
        "-o",
        "--output-dir",
        help="Output directory (default: <xp3_name>_extracted)",
        default=None,
    )
    p_extract.set_defaults(func=cmd_extract)
    p_pack = subparsers.add_parser(
        "pack",
        help="Pack a directory into an XP3 archive",
        description="Pack a directory into an XP3 archive.",
    )
    p_pack.add_argument(
        "input_dir",
        help="Directory to pack",
    )
    p_pack.add_argument(
        "output_xp3_path",
        help="Output XP3 archive path",
    )
    p_pack.add_argument(
        "-c",
        "--compress-level",
        type=int,
        default=6,
        metavar="LEVEL",
        help="zlib compression level (0-9, default: 6; 0 = no compression)",
    )
    p_pack.set_defaults(func=cmd_pack)
    p_list = subparsers.add_parser(
        "list",
        help="List files inside an XP3 archive",
        description="List files contained in an XP3 archive.",
    )
    p_list.add_argument(
        "xp3_path",
        help="Path to the XP3 archive",
    )
    p_list.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
