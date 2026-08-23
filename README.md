# 智慧文件整理 2.0（Windows）

一套完全在本機執行的掃描文件整理工具。程式會在 Windows 系統匣常駐，監聽指定資料夾，在新 PDF 或圖片寫入完成後執行 OCR，產生分類與檔名建議。

工具介紹與最新版下載：<https://smartdoc.leotsai.me/>

## 目前功能

- 監聽 PDF、JPG、PNG、TIFF、BMP；不以固定間隔輪詢，閒置時不進行 OCR。
- RapidOCR／ONNX Runtime 本機文字辨識，多頁 PDF 由 PyMuPDF 在記憶體中轉成影像。
- 擷取西元或民國日期、機關、主旨、文號，並分類為考核、會議紀錄、函文、簽呈、公告、契約、收據發票或表單。
- 安心模式預設開啟：所有新文件先進入待確認清單。
- 可按「掃描資料夾既有檔案」批次分析舊檔；資料庫指紋會略過已處理內容。
- 可選擇高信心自動改名，門檻預設 92%。
- 本機命名記憶：可選擇「保留原名並學習」，或在手動修改建議檔名後自動建立校正範例。
- 新文件只在 OCR 內容與既有範例達到相似度門檻時引用命名格式，並在判讀理由中顯示參考來源。
- `scan_001.pdf`、`IMG_401617.jpg` 等掃描器預設名稱不會加入學習；所有記憶都可在「命名記憶」頁查看與刪除。
- 可設定「分類 → 目的資料夾」歸檔規則；安心模式確認後移動，也可另外啟用高信心自動歸檔。
- 相對歸檔路徑會建立在監聽資料夾內，也可選擇其他磁碟的絕對路徑。
- 重名時自動加入 `_2`、`_3`，不覆蓋既有檔案。
- SQLite 保存處理、改名與移動紀錄，可復原原始檔名及位置。
- 同名檔案的檢查與移動會依序執行；資料庫寫入失敗時會嘗試把檔案補償移回原位。
- OCR 或分析暫時失敗時，可在「處理紀錄」重新加入辨識；程式意外中斷的文件會在下次啟動轉為可重試狀態。
- 待確認清單在背景更新時會保留已勾選項目與尚未套用的人工檔名。
- 使用完整 SHA-256 內容指紋；v0.3.0 舊指紋會在再次遇到原文件時自動升級。
- 選用 localhost AI；程式拒絕把文件送往非 loopback 網址。
- 登入 Windows 後自動啟動（使用目前使用者的啟動登錄，不需要系統管理員權限）。
- 同一位使用者一次只會執行一個程式實例；解除安裝時會清除開機啟動登錄。

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

程式不會修改文件內容；安心模式只有在確認後才會變更檔名或移動位置。設定與操作資料位於目前 Windows 使用者目錄：

- 設定：`%LOCALAPPDATA%\SmartDocumentOrganizer\settings.json`
- 紀錄：`%LOCALAPPDATA%\SmartDocumentOrganizer\documents.sqlite3`
- 記錄檔：`%LOCALAPPDATA%\SmartDocumentOrganizer\smartdoc.log`

不應把掃描資料夾設定成磁碟根目錄或多人共用的同步資料夾。正式導入公務環境前，建議先用副本資料夾測試命名規則。

相對歸檔路徑只能位於監聽資料夾內；如果確實需要歸檔到其他磁碟或資料夾，請在設定頁選擇絕對路徑。安裝檔目前尚未使用商用 Authenticode 憑證簽章，Windows SmartScreen 可能在第一次開啟時顯示來源提醒。

## localhost AI

設定頁可填入 OpenAI-compatible 本機服務，例如：

- 網址：`http://127.0.0.1:11434/v1/chat/completions`
- 模型：`qwen2.5:7b`

本機模型不可用、逾時或回傳格式不正確時，系統會自動退回內建規則分析，不會中斷文件處理。

## 本機命名記憶

命名記憶不會訓練或上傳大型模型，而是將你明確確認的檔名保存為本機校正範例：

1. 原始檔名正確時，按「保留原名並學習」。
2. 建議檔名需要修改時，直接在待確認表格中編輯後套用；程式會記住修改後的名稱。
3. 先前已處理的文件，可在「處理紀錄」選取後按「用目前檔名建立記憶」。
4. 不希望留下範例時，按「保留原名，不學習」；既有範例可到「命名記憶」頁刪除。

程式會把年度、日期、分類、主旨、機關或文號等可辨識部分轉成可變格式。例如從 `115年度教師成績考核名冊.pdf` 學到的規則，可在相似的次年度文件上建議 `116年度教師成績考核名冊.pdf`。

## 測試

```powershell
python -m pytest
```
