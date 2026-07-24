import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/LoginView.vue'),
    },
    {
      path: '/register',
      name: 'Register',
      component: () => import('../views/RegisterView.vue'),
    },
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
