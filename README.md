# Alpacon MCP 서버

이 프로젝트는 FastMCP 프레임워크 기반의 MCP 서버로, Alpacon API를 직접 호출하여 서버 관리, 웹셸, 웹FTP 등의 기능을 제공합니다.

## 1. 환경 준비

### uv 설치 (이미 설치했다면 생략)

```bash
pipx install uv  # 또는 brew install uv
```

### 가상환경 생성 및 패키지 설치

```bash
uv venv
source .venv/bin/activate
uv pip install mcp[cli] httpx
```

## 2. 토큰 설정

### 개발 환경 설정 (.config 디렉토리 사용)

개발용으로는 `.config` 디렉토리를 사용합니다:

```bash
# 개발 모드 환경변수 설정 (선택사항)
export ALPACON_DEV=true

# .config 디렉토리에 토큰 설정
mkdir -p .config
cp .config/token.json.example .config/token.json
# token.json 파일을 편집하여 실제 토큰 입력
```

### 프로덕션 환경 설정 (config 디렉토리 사용)

MCP 클라이언트에서 사용할 때는 `config` 디렉토리를 사용합니다:

```bash
mkdir -p config
# config/token.json 파일에 토큰 설정
```

### 토큰 파일 형식

```json
{
  "dev": {
    "alpacax": {
      "token": "your-dev-api-token-here",
      "workspace": "alpacax",
      "env": "dev"
    }
  },
  "prod": {
    "alpacax": {
      "token": "your-prod-api-token-here",
      "workspace": "alpacax",
      "env": "prod"
    }
  }
}
```

## 3. MCP 서버 실행

### Stdio 모드 (기본 MCP 모드)

```bash
python main.py
```

### SSE 모드 (Server-Sent Events)

```bash
python main_sse.py
```

### 직접 실행

```bash
# Stdio 모드
python -c "from server import run; run('stdio')"

# SSE 모드
python -c "from server import run; run('sse')"
```

## 4. 사용 가능한 MCP 도구

### 인증 관리
- `auth_set_token`: API 토큰 설정
- `auth_remove_token`: API 토큰 제거
- `alpacon_login`: Alpacon 서버 로그인 (기존 호환)
- `alpacon_logout`: Alpacon 서버 로그아웃 (기존 호환)

### 인증 자원 (Resources)
- `auth://status`: 인증 상태 확인
- `auth://config`: 설정 디렉토리 정보 확인
- `auth://tokens/{env}/{workspace}`: 특정 토큰 조회

## 5. 설정 디렉토리 우선순위

1. **개발 모드**: `.config` 디렉토리 우선 사용
   - `.config` 디렉토리가 존재하거나
   - `ALPACON_DEV=true` 환경변수가 설정된 경우

2. **프로덕션 모드**: `config` 디렉토리 사용
   - 일반적인 MCP 클라이언트 환경

3. **토큰 검색**: 설정된 디렉토리에서 토큰을 찾지 못하면 다른 디렉토리에서도 검색

## 6. 보안 주의사항

- `config/token.json`과 `.config/` 디렉토리는 `.gitignore`에 포함되어 Git에 커밋되지 않습니다
- 토큰 파일은 절대 공개 저장소에 업로드하지 마세요
- 개발용과 프로덕션용 토큰을 분리하여 관리하세요 