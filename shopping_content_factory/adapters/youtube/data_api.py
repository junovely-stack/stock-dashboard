"""YouTube Shorts 업로드 (YouTube Data API v3 videos.insert, resumable upload) + Analytics.

조사 결과 (docs/API_ACCESS_MATRIX.md):
- 업로드 쿼터: 2026-06 부터 'Video Uploads' 별도 버킷, 기본 하루 100회.
- 2026-11-02 revision: 미검증 프로젝트 업로드의 '비공개 고정'이 해제됨(이전 2020 규칙 폐지).
  그래도 공개 상태는 업로드 후 videos.list 로 다시 확인한다.
- status.containsSyntheticMedia: 실사형 AI·합성 콘텐츠 고지.
- paidProductPlacementDetails.hasPaidProductPlacement: 2026-11-16 부터 기본값 false 아님 → 명시 지정.
  일반 프로젝트에서 쓰기 가능한지 미확인 → 거절되면 해당 필드 없이 재시도하고 'Studio 수동 체크' 플래그.
- Shorts 판정: 3분 이하 + 세로/정사각. API 에 Shorts 전용 필드 없음.
- Shorts 설명란 URL 은 클릭 불가 → 구매 동선은 채널 프로필 링크/자체 랜딩.

업로드 PUT 은 재시도하지 않는다(중복 업로드 방지). 응답 불확실 시 UNKNOWN.
"""
from __future__ import annotations

import json
from pathlib import Path

from adapters.base import PublishResult
from app.models import PubStatus
from config.settings import Settings
from services.common.http import ExternalAPIError, HttpClient, HttpConfig, NotConfiguredError

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"


class YouTubePublisher:
    platform = "youtube"

    def __init__(self, settings: Settings, http: HttpClient | None = None):
        self.s = settings
        self.http = http or HttpClient("youtube", HttpConfig(max_retries=2, read_timeout=120))
        self.upload_http = HttpClient("youtube", HttpConfig(max_retries=0, read_timeout=600),
                                      session=self.http.session, recorder=self.http.recorder)
        self._token: str | None = None

    def missing_requirements(self) -> list[str]:
        return [n for n, v in [("YOUTUBE_CLIENT_ID", self.s.youtube_client_id),
                               ("YOUTUBE_CLIENT_SECRET", self.s.youtube_client_secret),
                               ("YOUTUBE_REFRESH_TOKEN", self.s.youtube_refresh_token)] if not v]

    def is_configured(self) -> bool:
        return not self.missing_requirements()

    def access_token(self) -> str:
        if self._token:
            return self._token
        resp = self.http.post(TOKEN_URL, operation="yt.oauth_refresh", data={
            "client_id": self.s.youtube_client_id, "client_secret": self.s.youtube_client_secret,
            "refresh_token": self.s.youtube_refresh_token, "grant_type": "refresh_token"})
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    @staticmethod
    def build_metadata(title: str, description: str, tags: list[str], synthetic: bool, privacy: str,
                       paid_placement: bool | None = True) -> dict:
        body = {
            "snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:15],
                        "categoryId": "26", "defaultLanguage": "ko"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": bool(synthetic)},
        }
        if paid_placement is not None:
            body["paidProductPlacementDetails"] = {"hasPaidProductPlacement": paid_placement}
        return body

    def publish(self, video_path: Path, title: str, description: str, tags: list[str],
                synthetic: bool) -> PublishResult:
        if not self.is_configured():
            raise NotConfiguredError(", ".join(self.missing_requirements()))
        headers = {"Authorization": f"Bearer {self.access_token()}", "Content-Type": "application/json"}
        manual_steps: list[str] = []
        meta = self.build_metadata(title, description, tags, synthetic, self.s.youtube_privacy_status)
        parts = "snippet,status,paidProductPlacementDetails"
        init = self.http.post(f"{UPLOAD_URL}?uploadType=resumable&part={parts}", operation="yt.upload_init",
                              headers=headers, data=json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        if init.status_code == 400 and "paidProductPlacement" in init.text:
            meta.pop("paidProductPlacementDetails", None)
            manual_steps.append("유료 프로모션 표시를 YouTube Studio 에서 직접 체크")
            init = self.http.post(f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
                                  operation="yt.upload_init", headers=headers,
                                  data=json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        if not init.ok or "Location" not in init.headers:
            return PublishResult(PubStatus.FAILED, error=f"업로드 세션 생성 실패 HTTP {init.status_code}",
                                 detail={"body": init.text[:500]})
        try:
            put = self.upload_http.request("PUT", init.headers["Location"], operation="yt.upload_put",
                                           headers={"Authorization": headers["Authorization"],
                                                    "Content-Type": "video/mp4"},
                                           data=video_path.read_bytes())
        except ExternalAPIError as exc:
            return PublishResult(PubStatus.UNKNOWN, error=f"업로드 응답 불확실 — Studio 에서 직접 확인: {exc}")
        if not put.ok:
            return PublishResult(PubStatus.FAILED, error=f"업로드 실패 HTTP {put.status_code}",
                                 detail={"body": put.text[:500]})
        video_id = put.json().get("id")
        return PublishResult(PubStatus.API_ACCEPTED, media_id=video_id,
                             url=f"https://www.youtube.com/shorts/{video_id}",
                             detail={"manual_steps": manual_steps, "requested_privacy": self.s.youtube_privacy_status})

    def verify(self, video_id: str) -> PublishResult:
        resp = self.http.get(VIDEOS_URL, operation="yt.verify",
                             headers={"Authorization": f"Bearer {self.access_token()}"},
                             params={"part": "status", "id": video_id})
        items = resp.json().get("items", []) if resp.ok else []
        if not items:
            return PublishResult(PubStatus.API_ACCEPTED, media_id=video_id, error="영상 조회 불가(처리 중)")
        status = items[0].get("status", {})
        if status.get("uploadStatus") in {"processed", "uploaded"} and status.get("privacyStatus") == "public":
            return PublishResult(PubStatus.PUBLISHED_VERIFIED, media_id=video_id,
                                 url=f"https://www.youtube.com/shorts/{video_id}", detail={"status": status})
        return PublishResult(PubStatus.API_ACCEPTED, media_id=video_id,
                             error=f"공개 게시 확인 안 됨 (privacy={status.get('privacyStatus')}, "
                                   f"upload={status.get('uploadStatus')})", detail={"status": status})

    def analytics(self, video_id: str, start: str, end: str) -> dict:
        """YouTube Analytics (데이터 지연 48~72시간). views 는 2025-03-31 부터 Shorts 재생·반복 포함."""
        resp = self.http.get(ANALYTICS_URL, operation="yt.analytics",
                             headers={"Authorization": f"Bearer {self.access_token()}"},
                             params={"ids": "channel==MINE", "startDate": start, "endDate": end,
                                     "metrics": "views,engagedViews,averageViewDuration,averageViewPercentage,"
                                                "likes,shares,subscribersGained",
                                     "filters": f"video=={video_id}"})
        resp.raise_for_status()
        data = resp.json()
        headers = [h["name"] for h in data.get("columnHeaders", [])]
        rows = data.get("rows") or []
        return dict(zip(headers, rows[0])) if rows else {}
