// 管理后台通用脚本 — 激活码/订单复制按钮（受 CSP 限制，必须用外部脚本）
function copyText(text, btn) {
  function done() {
    const old = btn.textContent;
    btn.textContent = '已复制';
    setTimeout(() => {
      btn.textContent = old;
    }, 1200);
  }
  function fallback() {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    done();
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done, fallback);
  } else {
    fallback();
  }
}

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('button[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      copyText(btn.getAttribute('data-copy'), btn);
    });
  });
});
