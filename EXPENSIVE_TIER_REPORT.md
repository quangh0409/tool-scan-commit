# Báo cáo: cơ chế SCAN của TẦNG ĐẮT (CodeQL · FindSecBugs · SonarQube)

> Tài liệu THIẾT KẾ — đọc & chốt TRƯỚC khi hiện thực Bước 2. Song song với
> `SCAN_MECHANISM.md` (tầng rẻ). Mục tiêu: nêu chính xác từng tool đắt quét thế nào,
> vì sao "đắt", thách thức đúng-đắn/chi-phí, và các QUYẾT ĐỊNH cần bạn chốt.
> ⚠️ Lệnh/flag/image dưới đây là DỰ KIẾN — sẽ PoC xác minh từng cái trước khi code
> (bài học trufflehog: không tin, phải kiểm).

---

## 0. Khác biệt CỐT LÕI so với tầng rẻ

| | Tầng RẺ (đã làm) | Tầng ĐẮT (Bước 2) |
|---|---|---|
| Đầu vào | **source thuần** (file text) | **artifact đã BUILD** (.class/.jar, hoặc DB trace build) |
| Phải compile? | KHÔNG | **CÓ — `mvn` phải chạy được tại commit đó** |
| Phạm vi quét | diff-scoped (file đổi) | **TOÀN module đã build** (không thể chỉ-diff) |
| Chi phí/commit | giây → phút | **nhiều phút → chục phút** (build + phân tích) |
| Rủi ro chính | over-scan, path | **BUILD FAIL** ở commit lịch sử; RAM; thời gian |
| Vai trò | candidate generator (recall) | **trọng tài chất lượng** (precision cao, có dataflow) |

→ Hệ quả kiến trúc: **KHÔNG chạy tầng đắt trên mọi commit.** Chỉ thả vào **top-K commit
được chọn** (núm chi phí). Build là nút thắt, KHÔNG phải bước phân tích.

---

## 1. CodeQL (GitHub) — phân tích dataflow trên "database" trích từ build

### Cơ chế
CodeQL KHÔNG đọc file text trực tiếp. Nó **dựng 1 database** bằng cách *quan sát quá trình
build* (với Java: chặn `javac`), rồi chạy **truy vấn** (.ql) trên DB đó.

1. **Tạo DB (đắt):**
   ```
   codeql database create <db> --language=java \
          --command="mvn -B clean compile -DskipTests"
   ```
   - Phải compile thành công thì DB mới đủ. Trace cả classpath/dependency.
2. **Phân tích:**
   ```
   codeql database analyze <db> \
          codeql/java-queries:codeql-suites/java-security-extended.qls \
          --format=sarif-latest --output=out.sarif
   ```
3. **Output:** SARIF 2.1.0 **native** (khỏi viết adapter). CWE nằm ở
   `rule.properties.tags` dạng `external/cwe/cwe-089` → parse trực tiếp.

### Đặc tính
- **Mạnh nhất** về taint/dataflow liên-thủ-tục, liên-file → bắt SQLi/XSS/path-traversal thực sự.
- **Image/CLI:** bundle `codeql` (CLI + query packs). Dự kiến đóng gói image riêng hoặc tải bundle.
- **Chi phí:** tạo DB ≈ thời-gian-build + trích xuất (vài phút); analyze 1–5 phút; DB ăn vài trăm MB→GB.
- **Điều kiện sống còn:** `mvn compile` phải chạy được tại commit. Fail build ⇒ không có DB.

---

## 2. Find Security Bugs (SpotBugs plugin) — phân tích BYTECODE

### Cơ chế
SpotBugs phân tích **bytecode .class/.jar**, KHÔNG phải source. Nên phải build trước
(`mvn package`/`compile` → ra `target/classes`).

```
spotbugs -textui -effort:max -low \
         -pluginList findsecbugs-plugin.jar \
         -xml:withMessages -output out.xml \
         target/classes            # hoặc các .jar module
```
hoặc qua Maven: `com.github.spotbugs:spotbugs-maven-plugin` + dependency `find-sec-bugs`.

- **Output:** SpotBugs **XML** → cần **adapter** (đã ghi trong CLAUDE.md). Mỗi `<BugInstance type=...>`
  có pattern (vd `SQL_INJECTION_JDBC`, `COMMAND_INJECTION`). Find-Sec-Bugs có **bảng pattern→CWE**
  (vd SQL_INJECTION_JDBC → CWE-89) → map sang `cwe`. Vị trí: `<SourceLine>` (class, start/end line).
- **Lưu ý đúng đắn:** line trong XML theo **source line của class đã compile** → cần khớp lại path
  source (`ClassName` → file `.java`). Bytecode-based nên có thể lệch dòng nếu build khác source.

### Đặc tính
- Nhẹ hơn CodeQL nhưng vẫn cần compile. Tốt cho Java/JVM, nhiều rule bảo mật.
- **Chỉ JVM** (Java/Scala/Kotlin) — không phủ JS/Python của train-ticket (ts-ui-dashboard).

---

## 3. SonarQube (lts-community, ephemeral) — server + scanner

### Cơ chế (2 tiến trình)
1. **Dựng server tạm:** `docker run -d sonarqube:lts-community` → chờ `/api/system/status` = UP (~1 phút, ~2GB RAM).
2. **Quét & đẩy lên server:** `sonar-scanner` (hoặc `mvn sonar:sonar`). Với Java cần **binaries đã build**:
   ```
   mvn -B clean compile -DskipTests
   sonar-scanner -Dsonar.host.url=http://localhost:9000 \
                 -Dsonar.login=<token> \
                 -Dsonar.java.binaries=**/target/classes \
                 -Dsonar.projectKey=<repo>@<sha>
   ```
3. **Lấy kết quả:** Web API `GET /api/issues/search?projectKeys=...&types=VULNERABILITY` → **JSON** → adapter.
   CWE qua security-standards: `GET /api/issues/search?...&facets=cwe` hoặc field `cwe` (cần xác minh schema bản LTS).

### Đặc tính
- **Nặng nhất về hạ tầng** (server JVM). Ephemeral: bật → quét → lấy issue → **tắt** (đừng để rò RAM).
- Cần `sonar.java.binaries` ⇒ vẫn phải compile.
- **Khác** CodeQL/SpotBugs: kết quả nằm trong server, phải gọi API kéo về (không xuất file thẳng).

---

## 4. Thách thức CHUNG (đây mới là phần khó, không phải "chạy tool")

1. **BUILD per-commit là nút thắt.**
   - train-ticket = Maven đa-module Spring Boot. `mvn compile` cần kéo dependency.
   - **Cache `~/.m2`:** mount kho .m2 dùng chung để khỏi tải lại mỗi commit. ⚠️ Song song nhiều build
     ghi cùng .m2 có thể đua → cân nhắc .m2 **read-only đã prime** + local-repo riêng mỗi worker, hoặc
     build TUẦN TỰ ở tầng đắt (K nhỏ nên chấp nhận).
2. **Build FAIL ở commit lịch sử** (rất thật): thiếu dep cũ, mã hỏng tạm thời, đổi JDK.
   - Phải xử lý "build_failed" như một TRẠNG THÁI ghi vào dataset (không phải crash), và tool đắt bỏ qua commit đó.
   - Cần chọn **JDK đúng thời kỳ** (train-ticket có thể cần Java 8). Maven toolchains.
3. **Phạm vi: tầng đắt quét TOÀN module, không diff-scoped.**
   - ⇒ tràn finding "nợ cũ" của toàn codebase. Phải **attribute về commit** bằng `finding_in_diff`
     (giao với dòng `added`) — y như tầng rẻ nhóm B, nhưng quy mô lớn hơn.
4. **RAM/đĩa:** CodeQL DB + Sonar server + Maven build song song → 32GB chia nhỏ nhanh. Tầng đắt nên
   chạy với **ít worker** (vd 1–2), tách biệt tầng rẻ.
5. **Tất định/tái lập:** pin version CLI + query-pack + image digest (ghi `run_meta`).

---

## 5. Kiến trúc PHỄU — chọn commit nào lên tầng đắt? ✅ ĐÃ HIỆN THỰC

Đây là **núm chi phí** chính (ngân sách GCP $300). Module `select_commits.py` + lệnh
`orchestrator select` đọc DB tầng rẻ và phân loại:
- **buggy (đáng nghi)** = commit có finding thuộc `SUSPECT_CATEGORIES` (mặc định **code/crypto/secret**;
  bỏ infra/info nhiễu) → **MỌI buggy đều lên tầng đắt**. Cờ `--require-in-diff 1` để chỉ tính lỗi
  commit-này-tạo.
- **clean (0 finding)** = negative thật → lấy **MẪU ngẫu nhiên tỉ lệ 1 buggy : N clean** (N = `CLEAN_PER_BUGGY`,
  mặc định **20**, CLI `--ratio`, seed tái lập).
- **xám** (chỉ infra/non-suspect) → BỎ (không đáng build, cũng không phải negative sạch).
- Ghi `selection_reason` (vd `suspect:code+secret`, `negative-sample(1:20)`) vào bảng **`selected_commits`**
  = hàng đợi cho tầng đắt.
- *Kiểm trên pilot run3:* universe 29 → 6 buggy + 12 clean (pool clean chỉ 12 < 20×6) → 18 commit cho tầng đắt.
- *Backlog:* thêm tín hiệu fix-commit (message "fix/CVE/security") để mine cặp vuln→fix.

---

## 6. Chuẩn hoá & CONSENSUS xuyên tầng

- CodeQL → **SARIF native** (CWE từ tags).
- FindSecBugs → SpotBugs **XML** → adapter → CWE (bảng pattern→CWE).
- Sonar → **Web API JSON** → adapter → CWE (security-standards).
- Cả 3 đổ về **cùng `RawFinding`** (schema hiện có) → `consensus()` gộp cụm theo `(file, nhóm-CWE, line±W)`
  **CHUNG với finding tầng rẻ** trên đúng commit đó. Khi đó VOTE_THRESHOLD có ý nghĩa thật: một SQLi được
  CodeQL + semgrep + (Sonar) cùng chỉ → `vuln` độ tin cao, kèm dataflow của CodeQL.
- Tầng đắt là nơi `vuln` code thực sự xuất hiện (tầng rẻ pilot cho 0 — đã xác nhận).

---

## 7. Rủi ro ĐÚNG ĐẮN cần canh (bài học trufflehog)

- **Khớp build ↔ commit:** DB/binaries phải đúng commit đang checkout (dùng clone-pool như tầng rẻ, nhưng cần checkout ĐẦY ĐỦ để build, không chỉ file đổi).
- **Lệch dòng bytecode↔source** (SpotBugs): kiểm vài ca tay.
- **CWE mapping mỗi tool mỗi kiểu:** chuẩn qua `cwe_groups.py`; map sai phá cụm.
- **Sonar API schema** khác giữa các bản LTS → PoC xác minh field CWE trước.
- **Phạm vi toàn-repo** → đừng gán nợ cũ thành "lỗi commit này": luôn kèm `finding_in_diff`.

---

## 8. Đề xuất PoC tối thiểu TRƯỚC khi code đầy đủ (chống lãng phí build)

1. **Chọn 1 commit train-ticket build được** (vd gần HEAD), `mvn -B clean compile -DskipTests` trong Docker → xác nhận compile OK + thời gian + JDK cần.
2. Trên đúng build đó, chạy LẦN LƯỢT 3 tool, xác minh: (a) ra finding, (b) lấy được CWE, (c) path/line khớp source.
3. Đo thời gian + RAM thực mỗi tool → ước tính K commit khả thi trong ngân sách.
4. Chỉ khi 3 cái trên xanh mới hiện thực wrapper + selection + adapter.

---

## 9. QUYẾT ĐỊNH cần bạn chốt

1. **Bộ tool tầng đắt:** cả 3 (CodeQL+FindSecBugs+Sonar) hay bắt đầu **chỉ CodeQL** (mạnh nhất, SARIF sẵn, ít hạ tầng hơn Sonar)?
2. **Chiến lược build:** build mỗi commit từ đầu (chậm, sạch) hay tái dùng `.m2` cache + incremental?
3. **Núm K:** số commit tối đa thả lên tầng đắt cho pilot (vd 10–30) để khớp ngân sách?
4. **Tiêu chí chọn commit** (mục §5) — ưu tiên cái nào?
5. **Xử lý build-fail:** ghi `build_failed` rồi bỏ, hay thử fallback (đổi JDK / `-DskipTests` / chỉ module đổi)?

→ Khuyến nghị của tôi: **bắt đầu CHỈ CodeQL** (giá trị/đơn-vị-công cao nhất, SARIF native, không cần server),
PoC 1 commit, K=10–20, chọn commit theo "có code-candidate + finding_in_diff=1", build-fail thì ghi & bỏ.
Thêm FindSecBugs/Sonar sau khi CodeQL chạy ổn.
