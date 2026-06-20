const app = getApp();

Page({
  data: {
    kids: [],
    selectedKid: null,
    records: []
  },

  onShow() {
    this.loadKids();
  },

  loadKids() {
    app.request({ url: '/api/kids' })
      .then(res => {
        this.setData({ kids: res.kids });
        if (res.kids.length > 0 && !this.data.selectedKid) {
          this.selectKid({ currentTarget: { dataset: { kid: res.kids[0] } } });
        }
      });
  },

  selectKid(e) {
    const kid = e.currentTarget.dataset.kid;
    this.setData({ selectedKid: kid });
    app.request({ url: `/api/kids/${kid.id}/records` })
      .then(res => this.setData({ records: res.records || [] }));
  },

  addKid() {
    wx.navigateTo({ url: '/pages/kids/add/add' });
  }
});
