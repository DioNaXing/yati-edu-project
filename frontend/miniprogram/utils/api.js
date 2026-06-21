// API 请求封装
// 备案前用 IP，备案后切换域名: https://api.yatitiyu.com
const API_BASE = 'https://yatitiyu.com';

function request(options) {
  const token = wx.getStorageSync('token') || '';
  return new Promise((resolve, reject) => {
    wx.request({
      url: API_BASE + options.url,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'Authorization': token ? `Bearer ${token}` : '',
        'Content-Type': 'application/json'
      },
      success(res) {
        if (res.statusCode === 200) {
          resolve(res.data);
        } else if (res.statusCode === 401) {
          wx.removeStorageSync('token');
          wx.reLaunch({ url: '/pages/index/index' });
          reject(res);
        } else {
          reject(res);
        }
      },
      fail: reject
    });
  });
}

// 手机号登录
function login(phone, code) {
  return request({
    url: '/api/auth/login',
    method: 'POST',
    data: { phone, code }
  }).then(res => {
    wx.setStorageSync('token', res.token);
    wx.setStorageSync('userInfo', res.user);
    return res;
  });
}

// 时间格式化
function formatTime(date, fmt = 'HH:mm') {
  const d = new Date(date);
  const o = {
    'YYYY': d.getFullYear(),
    'MM': String(d.getMonth() + 1).padStart(2, '0'),
    'DD': String(d.getDate()).padStart(2, '0'),
    'HH': String(d.getHours()).padStart(2, '0'),
    'mm': String(d.getMinutes()).padStart(2, '0'),
  };
  return fmt.replace(/YYYY|MM|DD|HH|mm/g, match => o[match]);
}

module.exports = { request, login, formatTime, API_BASE };
