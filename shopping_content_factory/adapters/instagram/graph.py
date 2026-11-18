"""Instagram Reels 게시 (공식 Instagram API with Instagram Login, graph.instagram.com).

조사 결과 (docs/API_ACCESS_MATRIX.md):
- 프로페셔널 계정(비즈니스/크리에이터) + instagram_business_content_publish 권한.
- 내 계정에만 쓰는 앱은 Standard Access 로 가능(App Review 불필요, 일부 기능 제한 가능성).
- video_url 은 공개 접근 가능한 URL 이어야 한다 → SCF_PUBLIC_MEDIA_BASE_URL 필수.
- 컨테이너 status_code: IN_PROGRESS → FINISHED → (게시 후) PUBLISHED / ERROR / EXPIRED(24h).
- 24시간 게시 한도(50 또는 100, 문서 간 불일치) → content_publishing_limit 으로 확인.
- is_ai_generated=true 로 AI 정보 라벨 지정 가능(2026-06 changelog).
- 제휴(수수료) 게시물은 Meta 정책상 '유료 파트너십' 라벨 대상 → API 지정 가능 여부 미확인, 수동 확인 단계로 둔다.

media_publish 는 재시도하면 중복 게시가 될 수 있어 재시도하지 않는다. 응답이 불확실하면 UNKNOWN.
"""
from __future__ import annotations

import time

from adapters.base import PublishResult
from app.models import PubStatus
from config.settings import Settings
from services.common.http import ExternalAPIError, HttpClient, HttpConfig, NotConfiguredError

GRAPH = "https://graph.instagram.com"


class InstagramPublisher:
    platform = "instagram"

    def __init__(self, settings: Settings, http: HttpClient | None = None, sleep=time.sleep,
                 poll_interval: float = 30.0, poll_max: int = 10):
        self.s = settings
        self.http = http or HttpClient("instagram", HttpConfig(max_retries=2))
        self.publish_http = HttpClient("instagram", HttpConfig(max_retries=0), session=self.http.session,
                                       recorder=self.http.recorder)
        self.sleep = sleep
        self.poll_interval = poll_interval
        self.poll_max = poll_max

    def missing_requirements(self) -> list[str]:
        missing = []
        if not self.s.instagram_user_id:
            missing.append("INSTAGRAM_USER_ID")
        if not self.s.instagram_access_token:
            missing.append("INSTAGRAM_ACCESS_TOKEN")
        if not self.s.media_base_url:
            missing.append("SCF_PUBLIC_MEDIA_BASE_URL (Meta 가 영상을 가져갈 공개 URL)")
        return missing

    def is_configured(self) -> bool:
        return not self.missing_requirements()

    def _url(self, path: str) -> str:
        return f"{GRAPH}/{self.s.instagram_graph_version}/{path}"

    def publish(self, video_url: str, caption: str, ai_generated: bool, trial: bool = False) -> PublishResult:
        if not self.is_configured():
            raise NotConfiguredError(", ".join(self.missing_requirements()))
        token = self.s.instagram_access_token
        params = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true",
                  "access_token": token}
        if ai_generated:
            params["is_ai_generated"] = "true"
        if trial:
            params["trial_params"] = '{"graduation_strategy":"MANUAL"}'
        resp = self.http.post(self._url(f"{self.s.instagram_user_id}/media"), operation="ig.create_container",
                              data=params)
        if not resp.ok:
            return PublishResult(PubStatus.FAILED, error=f"컨테이너 생성 실패 HTTP {resp.status_code}",
                                 detail={"body": resp.text[:500]})
        container_id = resp.json().get("id")
        status_code = "IN_PROGRESS"
        for _ in range(self.poll_max):
            st = self.http.get(self._url(container_id), operation="ig.container_status",
                               params={"fields": "status_code,status", "access_token": token})
            status_code = st.json().get("status_code", "IN_PROGRESS") if st.ok else "IN_PROGRESS"
            if status_code in {"FINISHED", "ERROR", "EXPIRED"}:
                break
            self.sleep(self.poll_interval)
        if status_code != "FINISHED":
            return PublishResult(PubStatus.FAILED, error=f"컨테이너 처리 상태 {status_code}",
                                 detail={"container_id": container_id})
        try:
            pub = self.publish_http.post(self._url(f"{self.s.instagram_user_id}/media_publish"),
                                         operation="ig.media_publish",
                                         data={"creation_id": container_id, "access_token": token})
        except ExternalAPIError as exc:
            return PublishResult(PubStatus.UNKNOWN, error=f"media_publish 응답 불확실 — 앱에서 직접 확인: {exc}",
                                 detail={"container_id": container_id})
        if not pub.ok:
            return PublishResult(PubStatus.FAILED, error=f"media_publish 실패 HTTP {pub.status_code}",
                                 detail={"container_id": container_id, "body": pub.text[:500]})
        media_id = pub.json().get("id")
        return PublishResult(PubStatus.API_ACCEPTED, media_id=media_id, detail={"container_id": container_id})

    def verify(self, media_id: str) -> PublishResult:
        resp = self.http.get(self._url(media_id), operation="ig.verify",
                             params={"fields": "id,permalink,timestamp,media_type",
                                     "access_token": self.s.instagram_access_token})
        if resp.ok and resp.json().get("permalink"):
            return PublishResult(PubStatus.PUBLISHED_VERIFIED, media_id=media_id, url=resp.json()["permalink"])
        return PublishResult(PubStatus.API_ACCEPTED, media_id=media_id, error="게시 확인 전")

    def insights(self, media_id: str) -> dict:
        metrics = "views,reach,likes,comments,saved,shares,total_interactions,ig_reels_avg_watch_time"
        resp = self.http.get(self._url(f"{media_id}/insights"), operation="ig.insights",
                             params={"metric": metrics, "access_token": self.s.instagram_access_token})
        resp.raise_for_status()
        out = {}
        for row in resp.json().get("data", []):  # 데이터가 없으면 빈 배열 (0 이 아님)
            values = row.get("values") or [{}]
            out[row["name"]] = values[0].get("value")
        return out
