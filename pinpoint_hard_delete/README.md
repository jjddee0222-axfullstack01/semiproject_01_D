# 회원 탈퇴: 소프트 삭제 → 하드 삭제

기준 커밋: `ef6797a` (GitHub main). GitHub는 변경하지 않았습니다.

## 적용 방법 (둘 중 하나)
- **패치**: 프로젝트 최상위 폴더에서 `git apply --check hard_delete.patch` → `git apply hard_delete.patch`
- **파일 복사**: `modified/` 안의 파일을 같은 경로에 덮어쓰기

DB 테이블·컬럼은 바꾸지 않습니다. 따라서 마이그레이션이나 테이블 재생성은 필요 없습니다.

## 바뀐 동작

| 구분 | 이전 (소프트 삭제) | 이후 (하드 삭제) |
|---|---|---|
| 계정 | `status = WITHDRAWN`으로 남음 | `users` 행 삭제 |
| 상품·리뷰·분석·답글·위험 키워드·세션·월별 통계 | 그대로 남음 | 외래키 `CASCADE`로 함께 삭제 |
| 의견 보내기(`feedbacks`) | 그대로 | 내용은 남고 작성자(`user_id`)만 NULL |
| 공용 키워드 사전(`keywords`) | 유지 | 유지 |
| 같은 이메일·사업자번호로 재가입 | 불가 (UNIQUE 충돌) | **가능** |

UNIQUE 제약(이메일, 사업자번호)은 **유지**합니다. 탈퇴하면 행이 사라지므로 재가입은 가능합니다. 제약을 없애면 같은 이메일로 계정이 여러 개 생겨 로그인 대상이 모호해집니다.

## 변경 파일
- `backend/auth.py`: `delete_account()` 추가. `DELETE FROM users` 한 번으로 처리하고, 나머지는 DB 외래키 규칙에 맡깁니다.
- `backend/main.py`, `backend/api_v1.py`: 화면 탈퇴와 API 탈퇴(`DELETE /api/v1/users/me`)가 모두 `delete_account()`를 사용합니다.
- `backend/models.py`: `UserStatus.WITHDRAWN` 주석만 변경했습니다 (미사용, 호환용으로 남김).
- `backend/templates/informationedit.html`: 탈퇴 확인 창에 "모든 데이터가 삭제되며 되돌릴 수 없다"는 경고를 추가했습니다.
- `backend/tests/test_pages.py`, `test_api_auth.py`: 삭제 범위, 재가입, 다른 셀러 데이터 보존, 의견 익명화 테스트를 추가·수정했습니다.
- `docs/02, 04, 05, 06`: 탈퇴 정책(D5)을 하드 삭제로 수정했습니다.

## 확인
```bash
cd backend
python -m pytest tests/test_pages.py tests/test_api_auth.py -v
python -m pytest
```

## 이미 소프트 탈퇴된 계정 정리 (선택)
이전 방식으로 탈퇴한 계정이 MariaDB에 남아 있으면, 그 이메일로는 여전히 재가입이 안 됩니다. 한 번만 실행하세요.
```sql
USE pinpoint;
DELETE FROM users WHERE status = 'WITHDRAWN';   -- 연결된 데이터도 CASCADE 로 함께 삭제됨
```
