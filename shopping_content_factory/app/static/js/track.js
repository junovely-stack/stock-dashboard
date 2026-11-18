// 최소 이벤트 기록: 페이지 조회·링크 클릭·영상 재생. 쿠키·IP·기기 정보 저장 없음.
(function () {
  var body = document.body;
  var base = {
    product_id: body.getAttribute("data-product") || null,
    content_id: body.getAttribute("data-content") || null,
    src: body.getAttribute("data-src") || "direct"
  };
  function send(type, extra) {
    var payload = JSON.stringify(Object.assign({ type: type }, base, extra || {}));
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon("/api/event", new Blob([payload], { type: "application/json" }));
      } else {
        fetch("/api/event", { method: "POST", body: payload, headers: { "Content-Type": "application/json" }, keepalive: true });
      }
    } catch (e) { /* 기록 실패는 사용자 경험에 영향 없음 */ }
  }
  if (base.product_id) { send("page_view"); }
  document.querySelectorAll("a.buy[data-link-id]").forEach(function (a) {
    // 이동은 브라우저 기본 동작 그대로 (자동 리디렉션 없음)
    a.addEventListener("click", function () { send("link_click", { link_id: a.getAttribute("data-link-id") }); });
  });
  var v = document.querySelector("video[data-track]");
  if (v) { v.addEventListener("play", function once() { send("video_play"); v.removeEventListener("play", once); }); }
})();
