<template>
  <Teleport to="body">
    <div class="drawing-panel" v-if="visible" :style="panelStyle" @click.stop>
      <div class="drawing-panel__tools">
        <button
          class="drawing-tool-btn"
          :class="{ 'drawing-tool-btn--active': toolMode === 'straight-line' }"
          @click="$emit('select-tool', 'straight-line')"
          title="直线"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="4" y1="20" x2="20" y2="4"/>
          </svg>
        </button>
        <button
          class="drawing-tool-btn"
          :class="{ 'drawing-tool-btn--active': toolMode === 'vertical-segment' }"
          @click="$emit('select-tool', 'vertical-segment')"
          title="竖直线"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="12" y1="3" x2="12" y2="21"/>
          </svg>
        </button>
        <span class="drawing-tools__sep"></span>
        <button
          class="drawing-tool-btn"
          :class="{ 'drawing-tool-btn--active': toolMode === 'v-shape' }"
          @click="$emit('select-tool', 'v-shape')"
          title="V"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="4,4 12,18 20,4"/>
          </svg>
        </button>
        <button
          class="drawing-tool-btn"
          :class="{ 'drawing-tool-btn--active': toolMode === 'inverted-v-shape' }"
          @click="$emit('select-tool', 'inverted-v-shape')"
          title="倒V"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="4,18 12,4 20,18"/>
          </svg>
        </button>
      </div>

      <div class="color-swatches">
        <button
          v-for="c in colorPresets"
          :key="c"
          class="color-swatch"
          :class="{ 'color-swatch--active': selectedColor === c }"
          :style="{ background: c }"
          @click="$emit('update:selectedColor', c)"
        />
        <label
          class="color-swatch color-swatch--custom"
          :style="{ background: selectedColor }"
          title="自定义颜色"
        >
          <input
            type="color"
            :value="selectedColor"
            class="color-swatch__input"
            @input="(e: any) => $emit('update:selectedColor', e.target.value)"
          />
        </label>
      </div>

      <button class="drawing-panel__clear-btn" v-if="drawingCount > 0" @click="$emit('clear-all')">
        清除 ({{ drawingCount }})
      </button>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import type { ToolMode } from '../composables/useDrawingTool'

defineProps<{
  visible: boolean
  toolMode: ToolMode
  selectedColor: string
  drawingCount: number
  panelStyle: Record<string, string>
}>()

defineEmits<{
  'select-tool': [mode: ToolMode]
  'update:selectedColor': [color: string]
  'clear-all': []
}>()

const colorPresets = ['#FFD700', '#FF6B6B', '#4FC3F7', '#81C784', '#CE93D8', '#FFB74D', '#FFFFFF']
</script>

<style scoped>
.drawing-panel {
  position: fixed;
  z-index: 100;
  background: #1a1e2e;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.55);
  padding: 6px 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  animation: dropdown-in var(--duration-fast, 150ms) var(--ease-out, ease-out);
}

.drawing-panel__tools {
  display: flex;
  gap: 3px;
  align-items: center;
}

.drawing-tools__sep {
  width: 1px;
  height: 20px;
  background: rgba(255, 255, 255, 0.12);
  margin: 0 2px;
  flex-shrink: 0;
}

.drawing-tool-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 6px;
  background: transparent;
  color: #9598A1;
  cursor: pointer;
  transition: all var(--duration-fast, 150ms);
}

.drawing-tool-btn:hover {
  color: #F8FAFC;
  border-color: rgba(255, 255, 255, 0.20);
  background: rgba(255, 255, 255, 0.04);
}

.drawing-tool-btn--active {
  color: #FFD700;
  border-color: rgba(255, 215, 0, 0.35);
  background: rgba(255, 215, 0, 0.08);
}

.color-swatches {
  display: flex;
  gap: 4px;
  align-items: center;
}

.color-swatch {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
  transition: border-color var(--duration-fast, 150ms);
  position: relative;
}

.color-swatch:hover {
  border-color: rgba(255, 255, 255, 0.5);
}

.color-swatch--active {
  border-color: #F8FAFC;
  box-shadow: 0 0 4px rgba(255, 255, 255, 0.25);
}

.color-swatch--custom {
  display: flex;
  align-items: center;
  justify-content: center;
  border-style: dashed;
  border-color: rgba(255, 255, 255, 0.20);
}

.color-swatch--custom::after {
  content: '+';
  color: rgba(255, 255, 255, 0.5);
  font-size: 12px;
  font-weight: 700;
  pointer-events: none;
  position: absolute;
}

.color-swatch__input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
  width: 100%;
  height: 100%;
}

.drawing-panel__clear-btn {
  padding: 4px 8px;
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.04);
  color: #9598A1;
  font-size: 10px;
  font-family: var(--font-sans, sans-serif);
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--duration-fast, 150ms);
}

.drawing-panel__clear-btn:hover {
  color: #e63535;
  border-color: rgba(230, 53, 53, 0.30);
  background: rgba(230, 53, 53, 0.06);
}
</style>
