// Gallery Item add/change form (Django Admin): shows the Photo field when
// Media Type = Photo, and the Video/Video Poster fields when Media Type =
// Video, so staff aren't stuck looking at irrelevant upload fields.
(function () {
  function fieldRow(name) {
    // Django admin wraps each field in a <div class="form-row field-<name>">
    return document.querySelector(".form-row.field-" + name);
  }

  function applyToggle(select) {
    var isVideo = select.value === "video";
    var imageRow = fieldRow("image");
    var videoRow = fieldRow("video");
    var posterRow = fieldRow("video_poster");
    if (imageRow) imageRow.style.display = isVideo ? "none" : "";
    if (videoRow) videoRow.style.display = isVideo ? "" : "none";
    if (posterRow) posterRow.style.display = isVideo ? "" : "none";
  }

  function init() {
    var select = document.getElementById("id_media_type");
    if (!select) return;
    applyToggle(select);
    select.addEventListener("change", function () {
      applyToggle(select);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
