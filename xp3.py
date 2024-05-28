import os
import zlib
import struct
import ctypes

W_CHAR_SIZE = ctypes.sizeof(ctypes.c_wchar)


class XP3Parser:
    def __init__(self, xp3_path: str = None):
        if xp3_path is None:
            raise ValueError("xp3_path cannot be None")
        self.xp3_path = xp3_path
        with open(self.xp3_path, 'rb') as f:
            self.xp3_data = f.read()

        if self.xp3_data[0:11] != bytes.fromhex('58 50 33 0D 0A 20 0A 1A 8B 67 01'):
            raise ValueError('Invalid XP3 header')

        self.file_manager_header_location = self.parse_xp3_header()

        file_manager_header = self.parse_file_manager_header(self.file_manager_header_location)
        self.is_file_manager_compressed, self.file_manager_compressed_size, self.file_manager_size = file_manager_header

        self.file_manager = self.get_file_manager(self.file_manager_header_location, *file_manager_header)
        self.file_manager = self.parse_file_manager(self.file_manager)

    def parse_xp3_header(self):
        if self.xp3_data[11:19] != bytes.fromhex('17 00 00 00 00 00 00 00'):
            return struct.unpack("<Q", self.xp3_data[11:19])[0]
        else:
            return struct.unpack("<Q", self.xp3_data[32:40])[0]

    def parse_file_manager_header(self, header_location):
        is_compressed = True if self.xp3_data[header_location] else False
        if is_compressed:
            compressed_size = struct.unpack("<Q", self.xp3_data[header_location + 1:header_location + 9])[0]
            uncompressed_size = struct.unpack("<Q", self.xp3_data[header_location + 9:header_location + 17])[0]
        else:
            compressed_size = 0
            uncompressed_size = struct.unpack("<Q", self.xp3_data[header_location + 1:header_location + 9])[0]
        return is_compressed, compressed_size, uncompressed_size

    def get_file_manager(self, header_location, is_compressed, compressed_size, uncompressed_size):
        if is_compressed:
            decompressed = zlib.decompress(self.xp3_data[header_location + 17:header_location + 17 + compressed_size])
        else:
            decompressed = self.xp3_data[header_location + 9:header_location + 9 + uncompressed_size]
        if len(decompressed) != uncompressed_size:
            raise ValueError('Invalid XP3 FileManager')
        return decompressed

    @staticmethod
    def parse_file_manager(file_manager: bytes):
        parsed_file_manager = []
        for i in range(len(file_manager)):
            if file_manager[i:i + 4] == b'File':
                i += 4
                file_manager_section_size = struct.unpack("<Q", file_manager[i:i + 8])[0]
                i += 8
                file_manager_section = file_manager[i:i + file_manager_section_size]
                parsed_file_manager_section = {}
                for j in range(len(file_manager_section)):
                    if file_manager_section[j:j + 4] == b'info':
                        j += 4
                        info_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        j += 8
                        if struct.unpack("<I", file_manager_section[j:j + 4])[0] == 1 << 31:
                            info_protect_flag = True
                        else:
                            info_protect_flag = False
                        j += 4
                        info_uncompressed_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        j += 8
                        info_storage_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        j += 8
                        info_file_name_size = struct.unpack("<H", file_manager_section[j:j + 2])[0] * W_CHAR_SIZE
                        j += 2
                        if info_size != 4 + 8 + 8 + 2 + info_file_name_size:
                            info_file_name_size = info_size - (4 + 8 + 8 + 2)
                            # raise ValueError('Invalid XP3 FileManager Info')
                        try:
                            info_file_name = str(file_manager_section[j:j + info_file_name_size], encoding='utf-16')
                        except Exception as e:
                            info_file_name = str(file_manager_section[j:j + info_file_name_size])
                        j += info_file_name_size
                        parsed_file_manager_section["info"] = {
                            "size": info_size,
                            "protect_flag": info_protect_flag,
                            "uncompressed_size": info_uncompressed_size,
                            "storage_size": info_storage_size,
                            "file_name_size": info_file_name_size,
                            "file_name": info_file_name
                        }

                    if file_manager_section[j:j + 4] == b"segm":
                        j += 4
                        segm_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        if segm_size % (4 + 8 + 8 + 8) != 0:
                            raise ValueError('Invalid XP3 FileManager Segment')
                        j += 8

                        segm = []
                        for _ in range(segm_size // (4 + 8 + 8 + 8)):
                            segm_compressed_flag = struct.unpack("<I", file_manager_section[j:j + 4])[0]
                            j += 4
                            segm_offset = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                            j += 8
                            segm_uncompressed_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                            j += 8
                            segm_storage_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                            j += 8

                            if segm_compressed_flag:
                                if segm_uncompressed_size == segm_storage_size:
                                    raise ValueError('Invalid XP3 FileManager Segment')
                            else:
                                if segm_uncompressed_size != segm_storage_size:
                                    raise ValueError('Invalid XP3 FileManager Segment')

                            segm.append({
                                "compressed_flag": True if segm_compressed_flag else False,
                                "offset": segm_offset,
                                "uncompressed_size": segm_uncompressed_size,
                                "storage_size": segm_storage_size
                            })
                        parsed_file_manager_section["segm"] = segm

                    if file_manager_section[j:j + 4] == b"adlr":
                        j += 4
                        adlr_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        j += 8
                        if adlr_size != 4:
                            raise ValueError('Invalid XP3 FileManager Adlr-32 checksum')
                        adlr = struct.unpack("<I", file_manager_section[j:j + adlr_size])[0]
                        j += adlr_size
                        parsed_file_manager_section["adlr"] = {
                            "size": adlr_size,
                            "adlr": adlr
                        }

                parsed_file_manager.append(parsed_file_manager_section)
                i += file_manager_section_size
            else:
                continue
        return parsed_file_manager

    def extract(self, output_dir: str = None):
        if output_dir is None:
            output_dir = os.path.dirname(self.xp3_path)
            base_name = os.path.splitext(os.path.basename(self.xp3_path))[0]
            output_dir = os.path.join(output_dir, base_name)

        for file in self.file_manager:
            file_info = file["info"]
            file_name = file_info["file_name"]
            segments = file["segm"]

            output_path = os.path.join(output_dir, file_name)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            with open(output_path, 'wb') as f:
                for segment in segments:
                    offset = segment["offset"]
                    storage_size = segment["storage_size"]
                    is_compressed = segment["compressed_flag"]

                    seg_data = self.xp3_data[offset:offset + storage_size]
                    if is_compressed:
                        seg_data = zlib.decompress(seg_data)
                    f.write(seg_data)
