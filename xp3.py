import ctypes
import hashlib
import os
import struct
import zlib
import mmap

W_CHAR_SIZE = ctypes.sizeof(ctypes.c_wchar)


class XP3Parser:
    def __init__(self, xp3_path: str):
        if xp3_path is None:
            raise ValueError("xp3_path cannot be None")
        self.xp3_path = xp3_path

        self.xp3_file = open(self.xp3_path, 'rb')
        self.xp3_size = os.path.getsize(self.xp3_path)
        self.xp3_data = mmap.mmap(self.xp3_file.fileno(), 0, access=mmap.ACCESS_READ)

        header_signature = bytes.fromhex('58 50 33 0D 0A 20 0A 1A 8B 67 01')
        index = self.xp3_data.find(header_signature)
        if index == -1:
            raise ValueError('Invalid XP3 header')
        else:
            if index != 0:
                self.xp3_data = self.xp3_data[index:]

        self.file_manager_header_location = self.parse_xp3_header()

        file_manager_header = self.parse_file_manager_header(self.file_manager_header_location)
        self.is_file_manager_compressed, self.file_manager_compressed_size, self.file_manager_size = file_manager_header

        self.file_manager = self.get_file_manager(self.file_manager_header_location, *file_manager_header)
        self.file_manager = self.parse_file_manager(self.file_manager)

    def __del__(self):
        if hasattr(self, 'xp3_data') and self.xp3_data:
            self.xp3_data.close()
        if hasattr(self, 'xp3_file') and self.xp3_file:
            self.xp3_file.close()

    def parse_xp3_header(self):
        if self.xp3_data[11:19] != bytes.fromhex('17 00 00 00 00 00 00 00'):
            return struct.unpack("<Q", self.xp3_data[11:19])[0]
        else:
            return struct.unpack("<Q", self.xp3_data[32:40])[0]

    def parse_file_manager_header(self, header_location):
        is_compressed = self.xp3_data[header_location] != 0

        if is_compressed:
            compressed_size = struct.unpack("<Q", self.xp3_data[header_location + 1:header_location + 9])[0]
            uncompressed_size = struct.unpack("<Q", self.xp3_data[header_location + 9:header_location + 17])[0]
        else:
            compressed_size = 0
            uncompressed_size = struct.unpack("<Q", self.xp3_data[header_location + 1:header_location + 9])[0]
        return is_compressed, compressed_size, uncompressed_size

    def get_file_manager(self, header_location, is_compressed, compressed_size, uncompressed_size):
        if is_compressed:
            compressed_data = self.xp3_data[header_location + 17:header_location + 17 + compressed_size]
            decompressed = zlib.decompress(compressed_data)
        else:
            decompressed = self.xp3_data[header_location + 9:header_location + 9 + uncompressed_size]
        if len(decompressed) != uncompressed_size:
            raise ValueError('Invalid XP3 FileManager')
        return decompressed

    @staticmethod
    def parse_file_manager(file_manager: bytes):
        parsed_file_manager = []
        i = 0
        file_manager_length = len(file_manager)
        while i < file_manager_length:
            index = file_manager.find(b'File', i)
            if index == -1:
                break
            else:
                i = index + 4
                if i + 8 > file_manager_length:
                    raise ValueError('Unexpected end of file manager data')
                file_manager_section_size = struct.unpack("<Q", file_manager[i:i + 8])[0]
                i += 8
                if i + file_manager_section_size > file_manager_length:
                    raise ValueError('Unexpected end of file manager data')
                file_manager_section = file_manager[i:i + file_manager_section_size]
                parsed_file_manager_section = {}
                j = 0
                while j < file_manager_section_size:
                    if file_manager_section[j:j + 4] == b'info':
                        j += 4
                        info_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        j += 8

                        protect_flag_value = struct.unpack("<I", file_manager_section[j:j + 4])[0]
                        info_protect_flag = (protect_flag_value & (1 << 31)) != 0
                        j += 4

                        info_uncompressed_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        j += 8

                        info_storage_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        j += 8

                        info_file_name_length = struct.unpack("<H", file_manager_section[j:j + 2])[0]
                        info_file_name_size = info_file_name_length * W_CHAR_SIZE
                        j += 2

                        expected_info_size = 4 + 8 + 8 + 2 + info_file_name_size

                        if info_size != expected_info_size:
                            info_file_name_size = info_size - (4 + 8 + 8 + 2)

                        info_file_name_data = file_manager_section[j:j + info_file_name_size]
                        try:
                            info_file_name = info_file_name_data.decode('utf-16-le').rstrip('\x00')
                        except UnicodeDecodeError:
                            md5 = hashlib.md5()
                            md5.update(info_file_name_data)
                            info_file_name = md5.hexdigest()
                        j += info_file_name_size

                        parsed_file_manager_section["info"] = {
                            "size": info_size,
                            "protect_flag": info_protect_flag,
                            "uncompressed_size": info_uncompressed_size,
                            "storage_size": info_storage_size,
                            "file_name_size": info_file_name_size,
                            "file_name": info_file_name
                        }
                    elif file_manager_section[j:j + 4] == b'segm':
                        j += 4
                        segm_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        j += 8

                        num_segments = segm_size // (4 + 8 + 8 + 8)
                        segm = []
                        for _ in range(num_segments):
                            segm_compressed_flag_value = struct.unpack("<I", file_manager_section[j:j + 4])[0]
                            segm_compressed_flag = bool(segm_compressed_flag_value)
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
                                "compressed_flag": segm_compressed_flag,
                                "offset": segm_offset,
                                "uncompressed_size": segm_uncompressed_size,
                                "storage_size": segm_storage_size
                            })
                        parsed_file_manager_section["segm"] = segm
                    elif file_manager_section[j:j + 4] == b'adlr':
                        j += 4
                        adlr_size = struct.unpack("<Q", file_manager_section[j:j + 8])[0]
                        j += 8
                        if adlr_size != 4:
                            raise ValueError('Invalid XP3 FileManager adlr checksum')
                        adlr = struct.unpack("<I", file_manager_section[j:j + adlr_size])[0]
                        j += adlr_size
                        parsed_file_manager_section["adlr"] = {"size": adlr_size, "adlr": adlr}
                    else:
                        break
                parsed_file_manager.append(parsed_file_manager_section)
                i += file_manager_section_size
        return parsed_file_manager

    def extract(self, output_dir: str = None):
        if output_dir is None:
            output_dir = os.path.dirname(self.xp3_path)
            base_name = os.path.splitext(os.path.basename(self.xp3_path))[0]
            output_dir = os.path.join(output_dir, base_name)

        for file in self.file_manager:
            file_info = file.get("info", {})
            file_name = file_info.get("file_name", "unnamed_file")

            output_path = os.path.join(output_dir, file_name)

            if len(output_path) > 260 or len(file_name) > 255:
                base_name, extension = os.path.splitext(file_name)
                max_base_name_length = min(259 - len(output_dir) - len(extension) - 1,
                                           254 - len(extension) - 1)
                base_name = base_name[:max_base_name_length]
                file_name = base_name + extension
                output_path = os.path.join(output_dir, file_name)

            segments = file.get("segm", [])

            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            with open(output_path, 'wb') as f_out:
                for segment in segments:
                    offset = segment["offset"]
                    storage_size = segment["storage_size"]
                    is_compressed = segment["compressed_flag"]

                    self.xp3_file.seek(offset)
                    seg_data = self.xp3_file.read(storage_size)
                    if is_compressed:
                        seg_data = zlib.decompress(seg_data)
                    f_out.write(seg_data)
