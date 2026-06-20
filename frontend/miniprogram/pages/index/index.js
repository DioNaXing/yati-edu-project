const app = getApp();

Page({
  data: {
    todayClasses: [],
    lessonsLeft: null,
    news: []
  },

  onLoad() {
    this.loadData();
  },

  onShow() {
    this.loadData();
  },

  loadData() {
    app.request({ url: '/api/dashboard' })
      .then(res => {
        this.setData({
          todayClasses: res.today_classes || [],
          lessonsLeft: res.lessons_left,
          news: res.news || []
        });
      })
      .catch(err => {
        wx.showToast({ title: '加载失败', icon: 'none' });
      });
  },

  goBooking() {
    wx.switchTab({ url: '/pages/booking/booking' });
  },

  goKids() {
    wx.switchTab({ url: '/pages/kids/kids' });
  },

  goProgress() {
    wx.navigateTo({ url: '/pages/progress/progress' });
  },

  goContact() {
    wx.navigateTo({ url: '/pages/contact/contact' });
  },

  goRecharge() {
    wx.navigateTo({ url: '/pages/payments/payments' });
  }
});
