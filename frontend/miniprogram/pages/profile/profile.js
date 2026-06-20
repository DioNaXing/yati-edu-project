Page({
  data: {
    userInfo: {}
  },

  onShow() {
    const user = wx.getStorageSync('userInfo');
    if (user) this.setData({ userInfo: user });
  },

  goKids() { wx.switchTab({ url: '/pages/kids/kids' }); },
  goPayments() { wx.navigateTo({ url: '/pages/payments/payments' }); },
  goContact() { wx.navigateTo({ url: '/pages/contact/contact' }); },
  goAbout() { wx.navigateTo({ url: '/pages/about/about' }); },
  goSettings() { wx.navigateTo({ url: '/pages/settings/settings' }); }
});
