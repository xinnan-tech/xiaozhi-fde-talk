import { h, defineComponent, type PropType } from "vue";
import { Icon as IconifyIcon, addIcon } from "@iconify/vue/dist/offline";

// Iconify Icon在Vue里本地使用（用于内网环境）
export default defineComponent({
  name: "IconifyIconOffline",
  components: { IconifyIcon },
  props: {
    icon: {
      type: [String, Object] as PropType<string | object | null>,
      default: null
    }
  },
  render() {
    if (typeof this.icon === "object" && this.icon !== null) {
      addIcon(
        JSON.stringify(this.icon),
        this.icon as Parameters<typeof addIcon>[1]
      );
    }
    const attrs = this.$attrs;
    if (typeof this.icon === "string") {
      return h(
        IconifyIcon,
        {
          icon: this.icon,
          "aria-hidden": false,
          style: attrs?.style
            ? Object.assign(attrs.style, { outline: "none" })
            : { outline: "none" },
          ...attrs
        },
        {
          default: () => []
        }
      );
    } else {
      if (this.icon === null) return null;
      return h(
        this.icon as Parameters<typeof h>[0],
        {
          "aria-hidden": false,
          style: attrs?.style
            ? Object.assign(attrs.style, { outline: "none" })
            : { outline: "none" },
          ...attrs
        },
        {
          default: () => []
        }
      );
    }
  }
});
