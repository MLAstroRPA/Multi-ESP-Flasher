# Multi-ESP-Flasher

Công cụ CLI **flash liên tục (multi-flash)** cho nhiều thiết bị **ESP32 / ESP8266** với quy trình **chọn loại ESP** → **chọn sản phẩm phần cứng** → **ghi nhớ lựa chọn file** cho từng sản phẩm.

## Loại ESP hỗ trợ (BƯỚC 1)

| Loại | `--chip` | Baud | File rời & offset |
|---|---|---|---|
| **ESP32** (mặc định) | `esp32` | 921600 | `bootloader.bin` `0x1000` · `partitions.bin` `0x8000` · `firmware.bin` `0x10000` · `spiffs.bin` `0x290000` |
| **ESP32-S3** | `esp32s3` | 921600 | `bootloader.bin` `0x0` · `partitions.bin` `0x8000` · `firmware.bin` `0x10000` · `spiffs.bin` `0x290000` |
| **ESP32-C3** | `esp32c3` | 921600 | `bootloader.bin` `0x0` · `partitions.bin` `0x8000` · `firmware.bin` `0x10000` · `spiffs.bin` `0x290000` |
| **ESP8266** | `esp8266` | 460800 | `firmware.bin` `0x0` · `spiffs.bin` `0x100000` |

Mọi loại đều có thêm mục **`combined.bin`** (file gộp/merged) → flash nguyên khối tại `0x0`.

- ESP32 / ESP32-S3 / ESP32-C3: trước khi flash, tool tự xóa vùng OTA boot data (`0xE000`, `0x2000`).
- ESP8266: **không** có vùng OTA này nên tool bỏ qua bước xóa.
- Muốn đổi offset/tốc độ nạp: sửa dict **`CHIP_PROFILES`** trong `Multi-ESP-Flasher.py`.

---

## Cách chạy

- Bản portable: nhấp đúp **`bin\Multi-ESP-Flasher.exe`** (không cần cài Python).
- Bản script: nhấp đúp **`Multi-ESP-Flasher.bat`** (cần Python 3 + `pip install esptool pyserial`).

## Quy trình

- **ĐANG KIỂM TRA ESP-TOOL-CLI** — kiểm tra ngầm; nếu OK vào thẳng BƯỚC 1 (không đếm ngược).

### BƯỚC 1 — Chọn loại ESP
- Danh sách: **ESP32** (mặc định) · **ESP32-S3** · **ESP32-C3** · **ESP8266**.
- Lựa chọn được **ghi nhớ** vào `Multi-ESP-Flasher.db.txt` (khoá `__chip__`) và tự nạp lại ở lần mở sau (có dấu `<- đã dùng lần trước`).
- Chọn bằng phím **↑/↓**, **Enter** xác nhận, **ESC** đóng ứng dụng.

### BƯỚC 2 — Chọn sản phẩm phần cứng
- Tool **quét các THƯ MỤC CON cùng cấp với file exe** (các thư mục nằm trong cùng thư mục chứa exe) và hiển thị danh sách sản phẩm.
- Nếu bin nằm ở nơi khác, chọn mục cuối **`Duyệt thư mục khác...`** → mở hộp thoại chọn thư mục (hủy hộp thoại = quay lại BƯỚC 2).
  - Thư mục vừa duyệt được **ghi nhớ** vào `Multi-ESP-Flasher.db.txt` (khoá = đường dẫn tuyệt đối, khoá `__browse_dir__` cho lần duyệt kế tiếp)
    và xuất hiện lại trong danh sách với tiền tố **`[ngoài]`**; nếu thư mục không còn tồn tại thì tự xóa khỏi db.
  - Nếu duyệt đúng một thư mục sản phẩm cạnh exe thì dùng luôn tên sản phẩm đó (không tạo mục `[ngoài]` trùng).
- Chọn bằng phím **↑/↓**, **Enter** chọn, **ESC** đóng ứng dụng, **R/F5** quét lại.
- Nếu **không có** thư mục sản phẩm nào cạnh exe, BƯỚC 2 chỉ còn mục `Duyệt thư mục khác...` — vẫn flash được bình thường.

### BƯỚC 3 — Chọn lần lượt các file bin cho sản phẩm
- Chọn **từng loại một** theo loại ESP đã chọn ở BƯỚC 1:
  - ESP32 / S3 / C3: `bootloader.bin`, `partitions.bin`, `firmware.bin`, `spiffs.bin`
  - ESP8266: `firmware.bin`, `spiffs.bin`
- Mục **cuối cùng** là **`combined.bin`** (file gộp/merged).
- Tool **tự phát hiện** file bin có sẵn trong thư mục sản phẩm và **ghi nhớ lựa chọn** vào file **`Multi-ESP-Flasher.db.txt`** (đặt cạnh exe).
- Mở lại ứng dụng sẽ **nạp lại** lựa chọn đã nhớ; nếu thư mục sản phẩm không còn tồn tại thì db được cập nhật (xóa mục cũ).
- Nếu chọn `combined.bin` → flash nguyên khối tại `0x0`; nếu không → flash các file rời theo offset ở bảng trên.

### BƯỚC 4 — Chọn chế độ
- `a)` **Auto multi flash** — sau khi flash, tự phát hiện cổng COM online và flash tiếp.
- `b)` **Confirm multi flash** — sau khi flash, đợi nhấn **Enter** để flash tiếp / **ESC** thoát.

### BƯỚC 5 — Quét & chọn cổng COM
- **↑/↓** chọn, **R/F5** quét lại, **Enter** chọn, **ESC** đóng ứng dụng.
- **Kiểm tra cổng đang bận:** sau khi chọn, tool mở thử cổng đó (giữ DTR/RTS thấp để không reset board).
  - Nếu cổng **đang bị ứng dụng khác mở** (N.I.N.A., WebUI MLAstroRPA serial terminal, Arduino IDE/PuTTY,
    cửa sổ Multi-ESP-Flasher khác…) → tool **tạm dừng**, hiện cảnh báo *CỔNG COM ĐANG BẬN* kèm gợi ý đóng cổng
    ở ứng dụng kia và chờ xác nhận:
    - **Enter** = tiếp tục flash với cổng đã chọn (sẽ lỗi nếu cổng còn bận)
    - **R** = kiểm tra lại (sau khi đã đóng ứng dụng kia)
    - **ESC** = hủy

### BƯỚC 6 — Vòng lặp flash
- **Auto:** flash xong → chờ rút/cắm USB → **đếm ngược 5s chống debounce** → tự flash tiếp; ESC thoát ngoài lúc flash; không thoát khi đang flash.
- **Confirm:** flash xong → **Enter** flash tiếp / **ESC** thoát.

### BƯỚC 7 — Báo cáo
- Hiển thị **`Số board đã nạp: XXX`** (to + đậm + đỏ) + dòng `Lỗi:` nếu có.
- Nhấn **Enter** hoặc **ESC** để đóng cửa sổ.

---

## File portable & đóng gói

- Exe: **`bin\Multi-ESP-Flasher.exe`** — bundle sẵn Python + esptool + pyserial + tkinter, chạy không cần cài gì.
- Toàn bộ **code tool** (build, splash, spec) nằm trong `.vscode\` (đã thêm vào `.gitignore`).
- Đóng gói lại sau khi sửa code: `.vscode\BUILD-PORTABLE.bat`.

### Dùng trên máy mới
- Không cần cài Python/esptool (exe bundle sẵn).
- Cần **driver USB-serial** của board (CH340/CP210x) nếu máy mới chưa có — không sẽ không thấy cổng COM.
- Exe không ký số → SmartScreen cảnh báo thì bấm *More info → Run anyway*.
- **Lưu ý quét sản phẩm:** ứng dụng quét các **thư mục con nằm trong cùng thư mục chứa file exe** (ví dụ exe ở `bin\MLAstro-Multi-ESP-Flasher.exe` → quét các thư mục bên trong `bin\`). Muốn thêm sản phẩm, chỉ cần tạo thư mục trong cùng thư mục exe và đặt các file bin vào đó. Bin nằm ở nơi khác thì dùng **`Duyệt thư mục khác...`** ở BƯỚC 2 (không cần copy vào `bin\`).
