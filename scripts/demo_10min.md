# Kịch bản demo hội đồng — 10 phút (`secjit-scan.exe`, run train-ticket `--max 30`)

> Chuẩn bị trước (không tính giờ): Docker Desktop đang chạy; đã có **Run A** (`pipeline --profile profiles/train-ticket-30.json`,
> xong hẳn, export + `run_manifest.json`) và **Run B** từ exe cùng profile; `review sample --seed 42` đã tạo mẫu nhưng chưa chấm hết;
> `compare --a <exportA> --b <exportB> --format md` đã dán sẵn vào `RESULTS.md`. Mở sẵn 1 cửa sổ PowerShell tại gốc repo.
> Nếu Docker không bật được trong phòng → bỏ bước 7 (Chạy thử 3 commit), nói rõ "demo đọc từ run đã có".

| # | Phút | Màn / lệnh | Thao tác | Câu nói mẫu |
|--:|--:|---|---|---|
| 1 | 0:00–0:45 | Mở `dist/secjit-scan.exe` → **Preflight** | Chỉ 13 mục: Docker daemon, RAM Docker, port Sonar, image, `max_map_count`… Bấm "Kiểm lại" | "Công cụ tự kiểm 13 điều kiện trước khi chạy — mọi lỗi hạ tầng (Docker tắt, đĩa đầy) được tách khỏi dữ liệu, không bao giờ biến thành nhãn sai." |
| 2 | 0:45–1:30 | **Home** → run `train-ticket --max 30` (Run A) | Chỉ registry: repo, nhánh, DB, export, trạng thái `done`, thời gian | "Mỗi run là một *profile* — một file JSON đủ để chạy lại y hệt bằng CLI. Đây là run 30 commit mới nhất của train-ticket, app Spring Boot 43 module." |
| 3 | 1:30–3:00 | **Results → Tổng quan** | Đi theo phễu: commit → sau lọc → buggy/clean → built/build_failed/skipped. Chỉ ô nhãn gold/silver/candidate, verified-clean/cheap-clean. Chỉ κ (tổng âm) rồi κ theo nhóm-CWE/cặp tool. Cuộn tới **Giới hạn** | "Phễu: tool rẻ quét mọi commit, tool đắt (FindSecBugs + Sonar, cần build Maven) chỉ vào commit đáng nghi và commit sạch để *xác minh*. Nhãn **gold ở đây là 'đồng thuận máy'** — chưa phải chân lý. κ tổng âm là bình thường và tôi sẽ giải thích ở phần hỏi đáp. Mọi bảng đều kèm danh sách giới hạn sinh tự động từ số liệu." |
| 4 | 3:00–4:00 | **Results → Finding** | Lọc `label=gold`, `cwe_group=csrf`; chỉ cột tools / n_agree / in_diff | "Một cụm = (file, nhóm CWE, dòng ±3). Cụm này 2 tool đắt cùng báo `csrf().disable()` trong SecurityConfig; `in_diff=1` nghĩa là chính commit này đưa dòng đó vào — đây là *lỗi do commit*, không phải nợ cũ." |
| 5 | 4:00–5:30 | **Finding → Bằng chứng** | Mở diff (dòng flag), tab tool_messages (rule_id Sonar/FindSecBugs), nút mở raw SARIF/XML, khối provenance (run_id, image digest, LINE_WINDOW, luật gold) | "Mọi nhãn truy ngược được tới output thô nguyên bản của từng tool và tới cấu hình đã dùng: digest image, tham số v1, commit của chính orchestrator. Không có bước nào 'tin lời' mô hình hay người." |
| 6 | 5:30–7:00 | **Kiểm tay (mù)** | Mở mẫu `seed=42`; chấm 2 mục: màn chỉ hiện code + CWE claim, **không** hiện tool/nhãn; chọn TP cho 1, FP (hoặc unclear) cho 1; bấm "Đóng mẫu" → precision + Wilson CI + Cohen κ (nếu 2 rater) | "Để biến 'đồng thuận máy' thành gold standard, chúng tôi lấy mẫu phân tầng theo nhóm CWE với seed cố định, chấm mù, 2 người độc lập. Kết quả là precision kèm khoảng tin cậy Wilson — và sau khi chấm, chỉ cụm **gold ✓ TP** mới được gọi là gold trong luận văn." |
| 7 | 7:00–8:30 | **Wizard → Chạy thử 3 commit** (sống) | Chọn repo train-ticket, "N commit gần nhất = 3", bỏ tick CodeQL; Dashboard hiện progress `scan start/item`… Có thể bấm "Dừng an toàn" để minh hoạ exit 3 | "Đây là chạy thật trên 3 commit để thấy tiến độ sống: mỗi dòng là một sự kiện JSON của `progress.jsonl`. 'Dừng an toàn' chỉ dừng ở ranh giới commit nên không bao giờ để lại dữ liệu nửa chừng." |
| 8 | 8:30–9:30 | PowerShell: lệnh CLI tương đương | Wizard 5 → "Sao chép lệnh"; dán: `python -m orchestrator.cli pipeline --profile …`; rồi `compare --a <A> --b <B> --format md` (đã chạy sẵn, chỉ hiện kết quả) | "GUI chỉ là vỏ: mỗi nút là đúng một lệnh CLI với cùng profile. Run A từ CLI và Run B từ exe cho **cùng số cụm theo nhãn**; mọi lệch — nếu có — phải nằm trong danh sách `tool_timeout/infra_error/skipped` của manifest, nếu không `compare` trả exit 1." |
| 9 | 9:30–10:00 | Tổng kết | Chỉ `METHODOLOGY.md` §1 (v1 đăng ký trước) và `sensitivity.md` | "Tham số gán nhãn được *đăng ký trước*, khoá trong profile; đổi tham số chỉ qua phân tích độ nhạy trên bản sao DB hoặc chế độ thí nghiệm được gắn cờ. Dataset công bố kèm manifest, SHA256SUMS và file chấm tay." |

## Câu hỏi hội đồng dự kiến & trả lời

**Q1. κ Fleiss âm (−0,3 … −0,5) — nghĩa là các tool "cãi nhau", vậy đồng thuận có ý nghĩa gì?**
κ tổng tính trên mọi cụm với *mẫu số* là tập tool đủ năng lực cho miền đó; các tool phủ **miền CWE rời nhau** (gitleaks chỉ secret, FindSecBugs bytecode, Sonar rule engine), nên trên phần lớn cụm chỉ 1 tool báo → agreement quan sát thấp hơn kỳ vọng ngẫu nhiên → κ âm. Đó là tín hiệu *sức khoẻ phủ*, không phải thước đo chất lượng nhãn. Vì thế chúng tôi (i) báo κ theo nhóm-CWE và theo **cặp tool** (vd findsecbugs|sonar dương), (ii) định nghĩa gold bằng số tool đồng thuận trong cụm, không bằng κ, (iii) kiểm tay để đo precision trực tiếp. (Tham chiếu: RULE_GAN_NHAN §7, METHODOLOGY §7.)

**Q2. "Gold" do máy đồng thuận có phải ground truth không?**
Không. Chúng tôi gọi rõ là **"gold · đồng thuận máy"** = *silver standard* (Rebholz-Schuhmann 2010); tool có lỗi tương quan. Chỉ cụm đã kiểm tay **TP** mới là gold standard (trường `evidence.validation`). Mẫu âm `verified-clean` cũng chỉ là "2 tool đắt không báo", có trong threats to validity.

**Q3. Làm sao biết không cherry-pick tham số để số đẹp?**
Tham số v1 (`LINE_WINDOW=3, GOLD_MIN_EXPENSIVE=2, 1E+1C=1, SILVER_MIN_CHEAP=2, NOISE={CWE-117}`) được **đăng ký trước** và khoá trong `profile.params_v1`; profile khác v1 bị từ chối trừ khi bật `experiment` kèm lý do, run gắn cờ, export tách `_exp`, không gộp vào gold_set. Ảnh hưởng tham số được báo bằng `sensitivity` (lưới W∈{3,5,7} × 1E+1C × noise) trên bản sao DB — số liệu chính không đổi theo kết quả đó. Test set (mẫu kiểm tay) chọn bằng seed cố định, chấm mù.

**Q4. Kết quả có tái lập được không?**
Có, ở 3 mức: (1) cùng profile → `compare` Run A (CLI) ↔ Run B (exe) khớp theo `cluster_key`, lệch chỉ ở commit hạ tầng được liệt kê trong manifest; (2) mọi run ghi `run_meta` (scope, env hiệu lực, digest image từng tool, git sha orchestrator, app version) và `SHA256SUMS`; (3) `verify --db --export` kiểm DB/export đúng hợp đồng (enum trạng thái, `n_expensive_ok`, nhãn tính lại từ `agreeing_tools` theo luật v1).

**Q5. Vì sao tầng đắt không phủ hết? Có thiên lệch không?**
Tầng đắt cần build Maven; commit lịch sử dùng dependency `*-SNAPSHOT` đã biến mất → `build_failed` (library Spring ~87 %, app thuần 8–46 %). Đó là thiên lệch external validity được khai báo: gold/verified-clean nghiêng về commit build được (thường gần đây). Số `build_failed/skipped/infra_error` có trong phễu và manifest, không bị gộp vào dữ liệu.

**Q6. Khác gì so với chỉ chạy một tool SAST?**
Một tool đơn lẻ FP cao (semgrep p/default, CWE-117 của FindSecBugs); đồng thuận chéo tầng (source-only vs build-based) giảm FP tương quan kỹ thuật, và quan trọng hơn: dataset giữ **raw của mọi tool** nên người dùng có thể định nghĩa lại nhãn (`relabel`) mà không quét lại.

**Q7. Dữ liệu âm (negative) lấy ở đâu, có tin được không?**
Commit 0 finding tầng rẻ → `cheap-clean`; nếu còn qua ≥2 tool đắt `ok` (không `skipped`) mà vẫn 0 lỗi `in_diff` → `verified-clean`. Đây là *reliable negative* theo nghĩa PU-learning, kèm 100 mẫu kiểm tay âm (`--n-neg 100`), và luôn ghi "không phải chứng minh sạch".

**Q8. Tool hỏng giữa run thì sao?**
Mỗi tool lỗi ghi `scan_tool_errors`/`expensive_runs.status` (`tool_timeout/tool_error/infra_error`); tool lỗi **không** được tính là "không báo" trong κ/mẫu số; `infra_error` đưa commit về `pending`, 3 lần liên tiếp → dừng run; vá tool rồi `rescan --commit SHA` chỉ chạy lại tool lỗi, giữ raw tool khác.

## Lệnh dự phòng (nếu GUI trục trặc)
```powershell
$env:PYTHONPATH='src'
python -m orchestrator.cli stats --db D:\secjit\results\dataset_train-ticket_30.sqlite --format json | more
python -m orchestrator.cli review --db D:\secjit\results\dataset_train-ticket_30.sqlite next --sample-id s42 --rater demo
python -m orchestrator.cli compare --a D:\secjit\results\export_A --b D:\secjit\results\export_B --format md
python -m orchestrator.cli pipeline https://github.com/FudanSELab/train-ticket --max 3 --codeql 0 --branch master
```
