// Prevent XSS: convert special characters like <, >, & into safe HTML entities
// so they display as text instead of being parsed as HTML/script tags.
function escapeHtml(str) {
  var div = document.createElement("div");
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}

function formatDate(isoString) {
  var d = new Date(isoString);
  var year = d.getFullYear();
  var month = String(d.getMonth() + 1).padStart(2, "0");
  var day = String(d.getDate()).padStart(2, "0");
  var hour = String(d.getHours()).padStart(2, "0");
  var minute = String(d.getMinutes()).padStart(2, "0");
  return year + "/" + month + "/" + day + " " + hour + ":" + minute;
}
