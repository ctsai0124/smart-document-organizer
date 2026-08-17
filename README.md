# 智慧文件整理 2.0（Windows）

一套完全在本機執行的掃描文件整理工具。程式會在 Windows 系統匣常駐，監聽指定資料夾，在新 PDF 或圖片寫入完成後執行 OCR，產生分類與檔名建議。

工具介紹與最新版下載：<https://smartdoc.leotsai.me/>

## 目前功能

- 監聽 PDF、JPG、PNG、TIFF、BMP；不以固定間隔輪詢，閒置時不進行 OCR。
- RapidOCR／ONNX Runtime 本機文字辨識，多頁 PDF 由 PyMuPDF 在記憶體中轉成影像。
- 擷取西元或民國日期、機關、主旨、文號，並分類為會議紀錄、函文、簽呈、公告、契約、收據發票或表單。
- 安心模式預設開啟：所有新文件先進入待確認清單。
- 可選擇高信心自動改名，門檻預設 92%。
- 重名時自動加入 `_2`、`_3`，不覆蓋既有檔案。
- SQLite 保存處理與改名紀錄，可復原檔名。
- 選用 localhost AI；程式拒絕把文件送往非 loopback 網址。
- 登入 Windows 後自動啟動（使用目前使用者的啟動登錄，不需要系統管理員權限）。

## 在開發模式執行

建議使用 Python 3.12：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install ".[dev]"
python -m smartdoc
```

第一次 OCR 時會載入本機模型，速度會比後續文件稍慢。模型與辨識內容都留在電腦上。

## 建立 Windows 應用與安裝程式

在 Windows PowerShell 執行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

輸出位置：

- 可執行程式：`dist\SmartDocumentOrganizer\SmartDocumentOrganizer.exe`
- 安裝程式：使用 Inno Setup 編譯 `installer\SmartDocumentOrganizer.iss` 後，輸出到 `dist\installer`

PyInstaller 不是跨平台編譯器，因此正式 Windows `.exe` 必須在 Windows 上執行上述腳本產生。

如果專案放在 GitHub，也可以到 Actions 手動執行 **Build Windows installer**；完成後會提供 `SmartDocumentOrganizer-Windows` 安裝檔成品，不必在開發電腦安裝 Windows 工具鏈。

## 本機資料位置

程式不會修改原始文件內容，只會在確認後變更檔名。設定與操作資料位於目前 Windows 使用者目錄：

- 設定：`%LOCALAPPDATA%\SmartDocumentOrganizer\settings.json`
- 紀錄：`%LOCALAPPDATA%\SmartDocumentOrganizer\documents.sqlite3`
- 記錄檔：`%LOCALAPPDATA%\SmartDocumentOrganizer\smartdoc.log`

不應把掃描資料夾設定成磁碟根目錄或多人共用的同步資料夾。正式導入公務環境前，建議先用副本資料夾測試命名規則。

## localhost AI

設定頁可填入 OpenAI-compatible 本機服務，例如：

- 網址：`http://127.0.0.1:11434/v1/chat/completions`
- 模型：`qwen2.5:7b`

本機模型不可用、逾時或回傳格式不正確時，系統會自動退回內建規則分析，不會中斷文件處理。

## 測試

```powershell
python -m pytest
```
