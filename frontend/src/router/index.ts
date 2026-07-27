import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'Kline',
      component: () => import('../views/KlineView.vue'),
    },
    {
      path: '/groups',
      name: 'Groups',
      component: () => import('../views/GroupsView.vue'),
    },
    {
      path: '/notifications',
      name: 'Notifications',
      component: () => import('../views/NotificationsView.vue'),
    },
  ],
})

export default router
