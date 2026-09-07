/* daemonkey-bus.js · 官方承诺的事件总线。MOD / user.js 只挂这里，不 fork chat.js。
 * 三件事: view:switch · message:render · sse:event
 * emit 返回 false = 有监听者 return false，官方那一步跳过。
 */
(function (g) {
  var DK = g.Daemonkey = g.Daemonkey || {};
  var hub = DK._hub || (DK._hub = {});

  DK.on = function (name, fn) {
    if (!name || typeof fn !== "function") return function () {};
    var list = hub[name] || (hub[name] = []);
    list.push(fn);
    return function () { DK.off(name, fn); };
  };

  DK.off = function (name, fn) {
    var list = hub[name];
    if (!list) return;
    hub[name] = list.filter(function (x) { return x !== fn; });
  };

  DK.emit = function (name, detail) {
    var list = (hub[name] || []).slice();
    var canceled = false;
    var payload = detail || {};
    for (var i = 0; i < list.length; i++) {
      try {
        if (list[i](payload) === false) canceled = true;
      } catch (err) {
        if (typeof console !== "undefined") console.warn("[Daemonkey]", name, err);
      }
    }
    return !canceled;
  };
})(typeof window !== "undefined" ? window : this);
