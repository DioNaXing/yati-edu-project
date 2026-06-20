const app = getApp();

Page({
  data: {
    kids: [],
    kidNames: [],
    selectedKid: '',
    selectedKidId: null,
    courses: [],
    courseId: null,
    dates: [],
    date: '',
    slots: [],
    slotId: null,
    canBook: false
  },

  onLoad() {
    this.loadKids();
    this.loadCourses();
    this.generateDates();
  },

  loadKids() {
    app.request({ url: '/api/kids' })
      .then(res => {
        const names = res.kids.map(k => k.name);
        this.setData({ kids: res.kids, kidNames: names });
      });
  },

  loadCourses() {
    app.request({ url: '/api/courses' })
      .then(res => this.setData({ courses: res.courses }));
  },

  generateDates() {
    const dates = [];
    const weekMap = ['周日','周一','周二','周三','周四','周五','周六'];
    for (let i = 0; i < 7; i++) {
      const d = new Date();
      d.setDate(d.getDate() + i);
      const full = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
      dates.push({ full, week: i === 0 ? '今天' : weekMap[d.getDay()], day: d.getDate() });
    }
    this.setData({ dates });
  },

  onKidChange(e) {
    const idx = e.detail.value;
    this.setData({
      selectedKid: this.data.kidNames[idx],
      selectedKidId: this.data.kids[idx].id
    });
    this.checkCanBook();
  },

  selectCourse(e) {
    this.setData({ courseId: e.currentTarget.dataset.id });
    this.checkCanBook();
    if (this.data.date) this.loadSlots();
  },

  selectDate(e) {
    this.setData({ date: e.currentTarget.dataset.date });
    this.checkCanBook();
    if (this.data.courseId) this.loadSlots();
  },

  loadSlots() {
    app.request({
      url: '/api/slots',
      data: { date: this.data.date, course_id: this.data.courseId }
    }).then(res => this.setData({ slots: res.slots }));
  },

  selectSlot(e) {
    if (e.currentTarget.dataset.booked) return;
    this.setData({ slotId: e.currentTarget.dataset.id });
    this.checkCanBook();
  },

  checkCanBook() {
    const { selectedKidId, courseId, date, slotId } = this.data;
    this.setData({ canBook: !!(selectedKidId && courseId && date && slotId) });
  },

  submitBooking() {
    app.request({
      url: '/api/bookings',
      method: 'POST',
      data: {
        kid_id: this.data.selectedKidId,
        course_id: this.data.courseId,
        date: this.data.date,
        slot_id: this.data.slotId
      }
    }).then(() => {
      wx.showToast({ title: '预约成功', icon: 'success' });
      setTimeout(() => wx.switchTab({ url: '/pages/index/index' }), 1500);
    }).catch(() => {
      wx.showToast({ title: '预约失败', icon: 'none' });
    });
  }
});
