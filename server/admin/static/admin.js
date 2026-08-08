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
  // 危险操作确认（data-confirm 表单提交前弹窗确认）
  document.querySelectorAll('form[data-confirm]').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      if (!window.confirm(f.getAttribute('data-confirm'))) {
        e.preventDefault();
      }
    });
  });
  document.querySelectorAll('[data-promotion-schedule]').forEach(function (root) {
    var hidden = root.querySelector('[data-promotion-dates]');
    var picker = root.querySelector('[data-promotion-date]');
    var chips = root.querySelector('[data-promotion-date-chips]');
    if (!hidden || !picker || !chips) return;
    var dates = (hidden.value || '').split(',').map(function (value) {
      return value.trim();
    }).filter(Boolean);

    function render() {
      dates = Array.from(new Set(dates)).sort();
      hidden.value = dates.join(',');
      chips.replaceChildren();
      dates.forEach(function (value) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'promotion-date-chip';
        chip.textContent = value + '  ×';
        chip.title = '移除此促销日期';
        chip.addEventListener('click', function () {
          dates = dates.filter(function (item) { return item !== value; });
          render();
        });
        chips.appendChild(chip);
      });
    }

    root.querySelector('[data-add-promotion-date]').addEventListener('click', function () {
      if (picker.value) {
        dates.push(picker.value);
        picker.value = '';
        render();
      }
    });
    root.querySelector('[data-clear-promotion-dates]').addEventListener('click', function () {
      dates = [];
      render();
    });
    render();
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
