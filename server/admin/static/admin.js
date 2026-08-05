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
  // 方案编辑：点"编辑"启用促销价/原价输入；提交前也确保提交（防 disabled 漏传）
  document.querySelectorAll('button[data-edit-form]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.getAttribute('data-edit-form');
      document.querySelectorAll('input[data-edit-form="' + id + '"]').forEach(function (i) {
        i.disabled = false;
      });
    });
  });
  document.querySelectorAll('form[id^="edit-"]').forEach(function (f) {
    f.addEventListener('submit', function () {
      document.querySelectorAll('input[data-edit-form="' + f.id + '"]').forEach(function (i) {
        i.disabled = false;
      });
    });
  });
});

// 滚动位置记忆：点击表单/链接提交后页面刷新回顶部，这里恢复原位置
(function () {
  var SCROLL_KEY = 'imgtrans_admin_scroll';
  var saved = sessionStorage.getItem(SCROLL_KEY);
  if (saved !== null) {
    sessionStorage.removeItem(SCROLL_KEY);
    window.addEventListener('load', function () {
      window.scrollTo(0, parseInt(saved, 10) || 0);
    });
  }
  document.addEventListener('click', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('form, a, button') : null;
    if (el) {
      sessionStorage.setItem(SCROLL_KEY, String(window.scrollY || window.pageYOffset || 0));
    }
  });
})();
