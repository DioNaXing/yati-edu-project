App({
  globalData: {
    apiBase: 'https://api.yatitiyu.com',
    token: '',
    userInfo: null,
    kids: []
  },

  onLaunch() {
    const token = wx.getStorageSync('token');
    if (token) {
      this.globalData.token = token;
      this.checkSession();
    }
  },

  checkSession() {
    wx.checkSession({
      fail: () => {
        this.globalData.token = '';
        wx.removeStorageSync('token');
      }
    });
  },

  request(options) {
    const { url, method = 'GET', data } = options;
    return new Promise((resolve, reject) => {
      wx.request({
        url: this.globalData.apiBase + url,
        method,
        data,
        header: {
          'Authorization': 'Bearer ' + this.globalData.token,
          'Content-Type': 'application/json'
        },
        success: (res) => {
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
});
