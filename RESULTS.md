# RESULTS — Nghiệm thu tái lập A/B `--max 30`

_Sinh lúc 2026-10-05T20:16:02 bởi `scripts/results_report.py`. Nhãn là ĐỒNG THUẬN MÁY (gold/silver/candidate), không phải chân lý; xem §7._

- **A**: `data\export_FudanSELab__train-ticket_master_20261005_A` (run_id `runA2-20261005`, DB: `data\dataset_FudanSELab__train-ticket_master_20261005_A.sqlite`)
- **B**: `data\export_FudanSELab__train-ticket_master_20261005_B` (run_id `r-20261005-120433-FudanSELab__train-ticket`, DB: `data\dataset_FudanSELab__train-ticket_master_20261005_B.sqlite`)

## Kết luận

✅ **ĐẠT tiêu chí tái lập** `--max 30`
- ⚠️ **orchestrator_git_sha khác: fd0a7cacdf079efb135e6bea9590bcf6906cab64 vs ad38710**

## 1. Cấu hình

| | A | B | khớp |
|---|---|---|:--:|
| params_v1.gold_allow_1exp_1cheap | 1 | 1 | ✓ |
| params_v1.gold_min_expensive | 2 | 2 | ✓ |
| params_v1.line_window | 3 | 3 | ✓ |
| params_v1.noise_cwe | ['CWE-117'] | ['CWE-117'] | ✓ |
| params_v1.silver_min_cheap | 2 | 2 | ✓ |
| orchestrator_git_sha | fd0a7cacdf079efb135e6bea9590bcf6906cab64 | ad38710 | ✗ |
| app_version | dev | ad38710 | ✗ |
| docker_version | 29.1.3 | 29.1.3 | ✓ |
| os | Windows-11-10.0.26200-SP0 | Windows-11-10.0.26200-SP0 | ✓ |
| experiment | None | None | ✓ |

### Image digest

| tool | image A | digest A | digest B | khớp |
|---|---|---|---|:--:|
| bearer | bearer version 2.1.1, build 600e551c56e61c063e425190d49fe0a960103a48 | `sha256:054087ae5045` | `sha256:054087ae5045` | ✓ |
| findsecbugs | orch-findsecbugs:1.14.0 | `sha256:d58fd1cb26db` | `sha256:d58fd1cb26db` | ✓ |
| gitleaks | v8.30.1 | `sha256:c00b6bd0aeb3` | `sha256:c00b6bd0aeb3` | ✓ |
| horusec | Version:           20.10.12 | `sha256:829fce13916b` | `sha256:829fce13916b` | ✓ |
| maven | maven:3.9-eclipse-temurin-8 | `sha256:0f402712b7a4` | `sha256:0f402712b7a4` | ✓ |
| semgrep | 1.178.0 | `sha256:32e459968daa` | `sha256:32e459968daa` | ✓ |
| sonar | sonarqube:lts-community | `sha256:f709975ab31d` | `sha256:f709975ab31d` | ✓ |
| trufflehog | trufflehog 3.97.9 | `sha256:52e67fef4d05` | `sha256:52e67fef4d05` | ✓ |

## 2. Phễu, nhãn và thời gian

| chỉ số | A | B | Δ (B−A) |
|---|---:|---:|---:|
| commits | 23 | 23 | 0 |
| clusters | 1691 | 1875 | 184 |
| gold | 3 | 3 | 0 |
| silver | 726 | 726 | 0 |
| candidate | 962 | 1146 | 184 |
| verified_clean | 1 | 1 | 0 |
| cheap_clean | 10 | 10 | 0 |
| build_failed | 1 | 1 | 0 |
| infra_error | 0 | 0 | 0 |
| skipped | 9 | 9 | 0 |
| tool_timeout | 1 | 0 | -1 |
| tool_error | 0 | 0 | 0 |

| thời gian | A | B |
|---|---|---|
| started (run_meta) | 2026-10-05T08:15:11 | 2026-10-05T12:05:14 |
| finished | 2026-10-05T10:09:27 | 2026-10-05T20:10:04 |
| thời lượng (giờ) | 1.904 | 8.081 |
| commit/giờ | 12.1 | 2.8 |
| tier có run_meta | analyze, scan | analyze, scan |

Build (speed.json, nguồn **default**, samples=0): cold 900 s · warm 180 s · FSB 10 s · Sonar 40 s · rẻ 12 s/commit.

## 3. So sánh cụm A/B (`orchestrator.compare`, theo cluster_key)

| same | only_a | only_b | label_changed | giải thích được | KHÔNG giải thích |
|---:|---:|---:|---:|---|---:|
| 1691 | 0 | 184 | 0 | tool_timeout=182, skipped=2 | **0** |

Cụm lệch (tối đa 20, chưa giải thích xếp trước):

| loại | commit | file | nhóm | nhãn | lý do |
|---|---|---|---|---|---|
| only_b | 4785de21 | ts-ui-dashboard/static/assets/js/vue-upload-component.js | sensitive_exposure | candidate | skipped (A) |
| only_b | 4785de21 | ts-ui-dashboard/static/assets/js/vue-upload-component.js | weak_random | candidate | skipped (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |
| only_b | fa8d9efb | deployment/docker-compose-manifests/docker-compose-with-jaeger.yml | permissions | candidate | tool_timeout (A) |

## 4. verify_run (CONTRACTS §1/§4/§6)

- **A**: PASS (18/18 mục)
- **B**: PASS (18/18 mục)

| mục | A | B |
|---|---|---|
| user_version | ✓ | ✓ |
| run_meta_scan | ✓ | ✓ |
| run_meta_analyze | ✓ | ✓ |
| run_meta_timestamps | ✓ | ✓ |
| expensive_status_enum | ✓ | ✓ |
| selected_no_stuck | ✓ | ✓ |
| n_expensive_ok_recount | ✓ | ✓ |
| verified_clean_rule | ✓ | ✓ |
| findings_cwe_group | ✓ | ✓ |
| findings_label_enum | ✓ | ✓ |
| gold_rule_v1 | ✓ | ✓ |
| label_rule_v1 | ✓ | ✓ |
| kappa_total | ✓ | ✓ |
| manifest_keys | ✓ | ✓ |
| manifest_counts | ✓ | ✓ |
| dataset_rows | ✓ | ✓ |
| commits_rows | ✓ | ✓ |
| sha256sums | ✓ | ✓ |

## 5. Fleiss' κ A vs B

| scope | nhóm | κ A (n) | κ B (n) | Δ |
|---|---|---:|---:|---:|
| total | — | -0.437 (1691) | -0.416 (1875) | 0.020 |
| category | code | -0.318 (219) | -0.289 (228) | 0.029 |
| category | crypto | -0.557 (21) | -0.355 (22) | 0.202 |
| category | info | -0.805 (96) | -0.469 (97) | 0.336 |
| category | infra | -0.471 (821) | -0.477 (992) | -0.006 |
| category | other | -0.265 (519) | -0.262 (521) | 0.003 |
| category | secret | -0.216 (15) | -0.216 (15) | 0.000 |
| cwe_group | CWE-113 | -0.250 (8) | -0.250 (8) | 0.000 |
| cwe_group | CWE-1357 | -0.500 (7) | -0.500 (7) | 0.000 |
| cwe_group | CWE-315 | -0.250 (12) | -0.250 (12) | 0.000 |
| cwe_group | CWE-346 | -0.250 (214) | -0.250 (214) | 0.000 |
| cwe_group | CWE-501 | -0.446 (6) | -0.320 (6) | 0.127 |
| cwe_group | CWE-614 | -0.250 (8) | -0.250 (8) | 0.000 |
| cwe_group | CWE-807 | -0.250 (5) | -0.250 (5) | 0.000 |
| cwe_group | CWE-915 | -0.250 (97) | -0.250 (97) | 0.000 |
| cwe_group | CWE-942 | -0.250 (151) | -0.250 (151) | 0.000 |
| cwe_group | csrf | -0.248 (204) | -0.259 (209) | -0.011 |
| cwe_group | hardcoded_secret | -0.216 (15) | -0.216 (15) | 0.000 |
| cwe_group | permissions | -0.471 (546) | -0.478 (705) | -0.008 |
| cwe_group | privilege | -0.471 (275) | -0.473 (287) | -0.001 |
| cwe_group | sensitive_exposure | -0.805 (96) | -0.469 (97) | 0.336 |
| cwe_group | sql_injection | — (—) | -0.500 (7) | — |
| cwe_group | weak_random | -0.557 (21) | -0.355 (22) | 0.202 |
| cwe_group | xss | -0.837 (12) | -0.470 (12) | 0.367 |

κ âm = tool phủ miền rời nhau (bình thường trên mọi repo); so Δ giữa A/B, không so giá trị tuyệt đối.

## 6. Tiêu chí tái lập

ĐẠT khi: `compare.unexplained = 0` (mọi lệch được giải thích bởi tool_timeout/infra_error/skipped/build_failed) **và** `verify_run` PASS cho cả A và B. Digest/params/git sha lệch là cảnh báo (làm lệch nhãn không quy được cho pipeline).

## 7. Giới hạn (từ `stats.limits`, nguồn: stats.overview(DB A))

- Tầng đắt không phủ 1/24 commit đã chọn (build_failed 4 %) — nhãn ở đó chỉ từ tool rẻ.
- 9 commit không có module Java (skipped) — không tính verified-clean.
- Secret trần (gitleaks/trufflehog) chỉ tới silver vì không có tool đắt xác nhận.
- CWE-117 đã lọc như nhiễu theo cấu hình v1 (raw vẫn giữ).
- Precision gold kiểm tay: 1/1 TP (CI95 0.21–1.00); nhãn còn lại là đồng thuận máy.
- κ Fleiss tổng -0.44 (âm) — tool phủ miền rời nhau; xem κ theo nhóm/cặp thay vì tổng.
- FindSecBugs và SonarQube cùng chạy nhưng 0 cụm liên-tool: hai tool neo cùng một lỗi vào mức cú pháp khác nhau (FSB tại khai báo method/field, Sonar tại statement). Đo trên DB này: 71 cặp cùng (file, nhóm CWE), khoảng cách dòng gần nhất min 13 · trung vị 40 · p90 43 (csrf 36–49; CWE-915 13–41; weak_random 53–110) — vượt mọi W∈{3,5,7} nên không gộp được; gold trên app Spring bị ước lượng thiếu có hệ thống và κ âm FSB–Sonar phần lớn phản ánh khác điểm neo, không phải bất đồng về lỗi (METHODOLOGY §8).

Khoảng cách điểm neo FSB↔Sonar (cùng file, nhóm CWE; 71 cặp): min 13 · trung vị 40 · p90 43 dòng.
| Nhóm CWE | n cặp | min | trung vị | max |
|---|--:|--:|--:|--:|
| csrf | 52 | 36 | 40 | 49 |
| CWE-915 | 17 | 13 | 22 | 41 |
| weak_random | 2 | 53 | 53 | 110 |

## 8. Ghi chú trung thực về quá trình chạy (trưởng nhóm bổ sung)

- **Phiên bản mã A ≠ B là có chủ đích, không phải lỗi tái lập.** A chạy từ mã nguồn (`a8f396e`, sau vá semgrep WinError 206). B chạy từ exe: tầng rẻ lúc 12:05 bằng exe `733576d`; tầng đắt chạy lại lúc 18:52 bằng exe `ad38710` sau khi phát hiện Sonar `tool_error` cả 5 commit (tên container theo `run_id` chứa chữ hoa và `__`, không hợp lệ làm hostname). Hotfix chỉ đổi tên container/network Sonar, đọc báo cáo horusec bằng UTF-8, và lấy git sha từ phiên bản exe — không đổi luật nhãn hay matcher.
- **Ba cụm gold của A đều sinh từ luật 1 tool đắt + 1 tool rẻ** (semgrep/bearer + Sonar, commit `e5ae0c3a`, `in_diff=0`). Không có cụm FindSecBugs–Sonar nào: hai tool neo cùng lỗi ở dòng khác nhau (trung vị lệch 40 dòng, 71 cặp). Xem `data/sens_A/sensitivity.md` và METHODOLOGY.md §8.
- **Lệch A/B duy nhất đến từ semgrep timeout** trên commit `fa8d9efb` (504 file) ở A; ở B semgrep chạy xong. Semgrep timeout theo rule là bất định đã biết (SESSION_CONTEXT 2026-07-07).
- Nhãn là đồng thuận máy, **chưa kiểm tay** (n = 0). Precision chỉ có sau khi chấm theo giao thức METHODOLOGY.md.
