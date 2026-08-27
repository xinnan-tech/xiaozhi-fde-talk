import type { Component } from "vue";

export interface SelectOption {
  label: string;
  value: string | number;
  disabled?: boolean;
  icon?: Component;
}
