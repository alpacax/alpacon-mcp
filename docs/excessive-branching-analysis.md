# 과도한 분기처리 분석 보고서

> **분석 대상**: `alpacon-mcp` 전체 28개 Python 파일
> **분석일**: 2026-04-30
> **발견 패턴**: 12개 (HIGH 4 / MEDIUM 6 / LOW 2)

---

## 요약

전체 코드베이스에서 **반복되는 분기 패턴 12개**를 발견했습니다. 가장 큰 문제는 **단순 dict 빌딩을 위한 `if x is not None` 체인**이 6개 파일에 걸쳐 71곳에서 반복되는 점입니다.

| 우선순위 | 항목 수 | 예상 코드 감소량 |
|----------|---------|------------------|
| HIGH     | 4       | ~500줄           |
| MEDIUM   | 6       | ~150줄           |
| LOW      | 2       | ~50줄            |

---

## HIGH (즉시 개선 권장)

### #1 — `if x is not None` 분기 폭발

**위치**: `tools/alert_tools.py:196-201`, `253-269` (특히 심함)
**영향 범위**: `alert_tools.py`, `security_tools.py`, `cert_tools.py`, `iam_tools.py`, `webhook_tools.py`, `approval_tools.py` 6개 파일에 71곳

**문제 코드**:
```python
# update_alert_rule — 옵셔널 8개를 위해 16줄 소비
update_data: dict[str, Any] = {}
if name is not None:
    update_data['name'] = name
if metric_type is not None:
    update_data['metric_type'] = metric_type
if condition is not None:
    update_data['condition'] = condition
if threshold is not None:
    update_data['threshold'] = threshold
if servers is not None:
    update_data['servers'] = servers
if notification_channels is not None:
    update_data['notification_channels'] = notification_channels
if description is not None:
    update_data['description'] = description
if enabled is not None:
    update_data['enabled'] = enabled
```

**왜 나쁜가**:
- 함수 본문의 70%가 단순 dict 빌딩으로 차지됨
- 필드 추가 시마다 if 블록 추가 필요
- 키 이름 오타 시 silent fail (긴 키 이름이 두 번 등장)

**개선 방안**:
```python
# utils/common.py
def filter_non_none(**kwargs) -> dict[str, Any]:
    """Build a dict, omitting keys whose value is None."""
    return {k: v for k, v in kwargs.items() if v is not None}

# 호출부 (16줄 → 8줄)
update_data = filter_non_none(
    name=name, metric_type=metric_type, condition=condition,
    threshold=threshold, servers=servers,
    notification_channels=notification_channels,
    description=description, enabled=enabled,
)
```

**예상 감소**: ~150줄

---

### #2 — 페이지네이션 파라미터 빌드 분기

**위치**: 거의 모든 `list_*` 함수 (`tools/*.py` 전체에 38곳)

**문제 코드**:
```python
params: dict[str, Any] = {}
if server_id:
    params['server'] = server_id
if status:
    params['status'] = status
if page is not None:
    params['page'] = page
if page_size is not None:
    params['page_size'] = page_size
```

**왜 나쁜가**:
- truthy 체크(`if server_id`)와 None 체크(`if page is not None`)가 섞여 있음
- `page=0` 같은 falsy 값이 의도치 않게 무시될 위험

**개선 방안**: `#1`의 `filter_non_none()`로 통합

**예상 감소**: ~100줄

---

### #3 — `request()` 메서드: 188줄 단일 메서드 + retry 로직 3중 복제

**위치**: `utils/http_client.py:259-446`

**문제 코드** (3개 except 블록에 동일 패턴 복붙):
```python
# except httpx.HTTPStatusError (500): 377-386
if e.response.status_code >= 500:
    retry_count += 1
    logger.warning(f'Server error, retrying ({retry_count}/{self.max_retries}) in {retry_delay}s')
    if retry_count < self.max_retries:
        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, self.max_retry_delay)
        continue

# except httpx.TimeoutException: 401-417
retry_count += 1
logger.warning(f'Request timeout, retrying ({retry_count}/{self.max_retries}) in {retry_delay}s')
if retry_count < self.max_retries:
    await asyncio.sleep(retry_delay)
    retry_delay = min(retry_delay * 2, self.max_retry_delay)
    continue

# except httpx.RequestError: 419-432
retry_count += 1
logger.warning(f'Network error: {e}, retrying ({retry_count}/{self.max_retries}) in {retry_delay}s')
if retry_count < self.max_retries:
    await asyncio.sleep(retry_delay)
    retry_delay = min(retry_delay * 2, self.max_retry_delay)
    continue
```

추가로 `_is_cacheable(method, url)` 호출이 **321, 354, 363줄에서 3번** 반복됨.

**왜 나쁜가**:
- retry backoff 정책 변경 시 3곳을 동시에 수정해야 함
- 188줄 단일 메서드는 cyclomatic complexity가 매우 높아 테스트가 어려움
- 분기 깊이 4단계로 흐름 추적이 힘듦

**개선 방안**:
```python
async def _retry_loop(self, attempt_fn):
    """Wrap an awaitable with exponential backoff retry."""
    retry_delay = self.retry_delay
    for retry_count in range(self.max_retries):
        try:
            return await attempt_fn()
        except (httpx.TimeoutException, httpx.RequestError, ServerError) as e:
            if retry_count + 1 >= self.max_retries:
                raise
            logger.warning(f'Retry {retry_count + 1}/{self.max_retries}')
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, self.max_retry_delay)
```

**예상 감소**: 188줄 → ~80줄

---

### #4 — `parse_*_metrics`: 임계값만 다른 동일 함수 4개

**위치**: `tools/metrics_tools.py:14-72` (CPU), `134-183` (Memory), disk, network

**문제 코드**:
```python
# parse_cpu_metrics
def get_status(usage):
    if usage < 20:   return 'idle'
    elif usage < 50: return 'low'
    elif usage < 70: return 'moderate'
    elif usage < 90: return 'high'
    else:            return 'critical'

return {
    'available': True,
    'current_usage_percent': f'{current:.2f}%',
    ...
    'health': 'healthy' if current < 80 else 'warning' if current < 95 else 'critical',
}

# parse_memory_metrics — 100% 동일 구조, 임계값(30/60/80/95)만 다름
def get_status(usage):
    if usage < 30:   return 'idle'
    elif usage < 60: return 'low'
    ...
```

**왜 나쁜가**:
- "데이터 추출 → 통계 계산 → 응답 포맷팅" 알고리즘이 4번 반복
- 새 메트릭 추가 시 60줄 복붙
- 임계값 정책 변경 시 4곳 수정

**개선 방안**:
```python
THRESHOLDS = {
    'cpu':    {'status': (20, 50, 70, 90), 'health': (80, 95)},
    'memory': {'status': (30, 60, 80, 95), 'health': (85, 95)},
    'disk':   {'status': (...),            'health': (...)},
    'network':{'status': (...),            'health': (...)},
}
STATUS_LABELS = ['idle', 'low', 'moderate', 'high', 'critical']
HEALTH_LABELS = ['healthy', 'warning', 'critical']

def classify(value, breakpoints, labels):
    for bp, label in zip(breakpoints, labels):
        if value < bp:
            return label
    return labels[-1]

def parse_metrics(results, metric_type):
    # 공통 로직 1번만
    cfg = THRESHOLDS[metric_type]
    return {
        'status': classify(current, cfg['status'], STATUS_LABELS),
        'health': classify(current, cfg['health'], HEALTH_LABELS),
        ...
    }
```

**예상 감소**: 240줄 → ~80줄

---

## MEDIUM (개선 권장)

### #5 — `isinstance(result, dict/list)` 삼항 분기 반복
**위치**: `tools/metrics_tools.py:126-127, 246-247, 408-409, 626-627`

```python
parsed = (
    parse_cpu_metrics(result.get('results', []))
    if isinstance(result, dict)
    else parse_cpu_metrics(result if isinstance(result, list) else []),
)
```
→ `_normalize_results()` 헬퍼 1개로 통합

---

### #6 — `extract_summary()` 4단계 중첩
**위치**: `tools/metrics_tools.py:916` (7개 반환 경로)

`isinstance` 체크 → `'results' in result` 체크 → metric_type 분기 → 각각 다른 추출 로직. 단일 함수에 4단계 분기.

---

### #7 — `command_tools.py` parallel/sequential 결과 분류
parallel 실행 결과와 sequential 결과를 각각 다르게 분류하는 분기가 중복.

---

### #8 — `with_token_validation`: `auth_enabled` 4번 분기
**위치**: `utils/decorators.py:270, 274, 283, 318`

```python
auth_enabled = _is_auth_enabled()        # 270: 한 번 계산

if auth_enabled:                          # 274: 분기 1
    jwt_token = _get_jwt_token()

if not region:
    if auth_enabled:                      # 283: 분기 2
        resolved_region = _resolve_region_jwt(...)
    else:
        resolved_region = _resolve_region_local(...)

if auth_enabled:                          # 318: 분기 3
    if not _validate_jwt_workspace(...):
        ...
else:
    token = validate_token(region, workspace)
```

**왜 나쁜가**: 두 모드(stdio / streamable-http)의 코드가 한 함수에 인터리빙되어 흐름 추적이 어렵고 모드별 단위 테스트가 힘듦.

**개선**: 전략 패턴 (`StdioAuth` / `JwtAuth` 클래스로 분리)

---

### #9 — `TokenManager.__init__`: 3단계 중첩 if/elif
**위치**: `utils/token_manager.py:23-52`

```python
if config_file:                       # Level 1
    ...
else:
    if env_config_file:               # Level 2
        ...
    else:
        if global_config.exists():    # Level 3
            ...
        elif local_config.exists():
            ...
        else:
            self.token_file = global_config  # 중복
```

**개선**: Early return + 우선순위 리스트
```python
def _resolve_config_path(config_file: str | None) -> Path:
    if config_file:
        return Path(os.path.expanduser(config_file))
    if env := os.getenv('ALPACON_MCP_CONFIG_FILE'):
        return Path(os.path.expanduser(env))

    global_config = Path.home() / '.alpacon-mcp' / 'token.json'
    local_config = Path('config/token.json')
    for candidate in (global_config, local_config):
        if candidate.exists():
            return candidate
    return global_config  # default
```

---

### #10 — `server.py:_create_mcp_server`
검증 로직과 빌드 로직이 혼합되어 있고, FastMCP 빌더 호출이 분기마다 반복됨.

---

## LOW (선택적)

### #11 — `webftp_tools.py` upload/download S3 분기 골격 중복
업로드/다운로드 흐름의 S3 presigned URL 처리 골격이 매우 유사하나 작은 차이로 분리됨.

### #12 — `http_client.py:_handle_upstream_401`
`mfa_required` 삼항식이 응답 빌더 안에 산재되어 있음.

```python
'error': 'MFA Required' if mfa_required else 'HTTP Error',
'message': 'MFA verification required' if mfa_required else str(exc),
```

---

## 권장 진행 순서

| 단계 | 항목 | 이유 | 효과 |
|------|------|------|------|
| 1 | #1 + #2 (`filter_non_none()`, `build_query_params()` 헬퍼) | 가장 광범위, 위험도 낮음 | ~250줄 즉시 감소 |
| 2 | #3 (`request()` retry 추출) | 핵심 인프라 단순화 | 188줄 → 80줄 |
| 3 | #4 (메트릭 통합 parser) | 도메인 가치 높음 (정책 단일화) | 240줄 → 80줄 |
| 4 | #9 (token_manager early return) | 작고 안전 | 30줄 → 12줄 |
| 5 | #8 (auth 전략 패턴) | 구조 변경, 신중하게 | 95줄 → 30+30줄 |

---

## 종합 임팩트

| # | 영향 범위 | 코드 감소 |
|---|-----------|-----------|
| #1 + #2 | 6개 파일, 109곳 | ~250줄 |
| #3 | http_client 1개 메서드 | ~108줄 |
| #4 | metrics_tools.py 4개 함수 | ~160줄 |
| #8 | decorators.py 1개 함수 | ~35줄 |
| #9 | token_manager.py 1개 메서드 | ~18줄 |
| **합계** | | **~571줄 감소 가능** |

---

## 참고

- 모든 개선은 **기능 동작 변경 없이** 가능 (pure refactoring)
- 헬퍼 추가 후 각 호출부를 점진적으로 마이그레이션 가능 (한 번에 다 바꿀 필요 없음)
- 테스트 커버리지가 충분하지 않은 영역(`http_client.request()`)은 리팩터링 전에 테스트 보강 권장
