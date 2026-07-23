(function ($, elementor) {
  $(window).on("elementor/frontend/init", function () {
    const ModuleHandler = elementorModules.frontend.handlers.Base;

    class HorizontalScroller extends ModuleHandler {
      bindEvents() {
        this.run();
      }

      getDefaultSettings() {
        return {
          allowHTML: true,
        };
      }

      settings(key) {
        return this.getElementSettings(`horizontal_scroller_${key}`);
      }

      sectionJoiner() {
        const widgetID = this.$element.data("id");
        const sectionList = this.settings("section_list");
        const widgetWrapper = `.elementor-element-${widgetID} .bdt-ep-hc-wrapper`;

        const sectionIds = sectionList
          .map((section) => `#${section.horizontal_scroller_section_id}`)
          .filter((id) => document.querySelector(id));

        if (!sectionIds.length) return;

        const selectedElements = document.querySelectorAll(
          sectionIds.join(", ")
        );
        $(widgetWrapper).append(selectedElements);
      }

      horizontalScroller() {
        gsap.registerPlugin(ScrollTrigger, ScrollToPlugin);

        const widgetID = this.$element.data("id");
        const widgetWrapper = `.elementor-element-${widgetID} .bdt-ep-hc-wrapper`;
        const scroller = document.querySelector(widgetWrapper);
        const navLis = document.querySelectorAll(`${widgetWrapper} nav li`);

        let sections = gsap.utils.toArray(
          `${widgetWrapper} > .elementor-element`
        );
        if (!sections.length) return;

        const numSections = sections.length - 1;
        const snapVal = 1 / numSections;
        const optionSnap = this.settings("auto_fill") ? snapVal : false;
        let lastIndex = 0;

        const tween = gsap.to(sections, {
          xPercent: -100 * numSections,
          ease: "none",
          scrollTrigger: {
            trigger: widgetWrapper,
            pin: true,
            scrub: true,
            snap: optionSnap,
            end: () => `+=${scroller.scrollWidth - innerWidth}`,
            onUpdate: (self) => {
              const newIndex = Math.round(self.progress / snapVal);
              if (this.settings("show_dots") && newIndex !== lastIndex) {
                navLis[lastIndex].classList.remove("is-active");
                navLis[newIndex].classList.add("is-active");
                lastIndex = newIndex;
              }
            },
          },
        });

        navLis.forEach((anchor, i) => {
          anchor.addEventListener("click", () => {
            gsap.to(window, {
              scrollTo: {
                y: tween.scrollTrigger.start + i * innerWidth,
                autoKill: false,
              },
              duration: 1,
            });
          });
        });
      }

      run() {
        if (elementorFrontend.isEditMode()) return;

        const widgetID = this.$element.data("id");
        const widgetContainer = `.elementor-element-${widgetID}`;

        ScrollTrigger.matchMedia({
          "(min-width: 1024px)": () => {
            $(widgetContainer).addClass("bdt-ep-hc-active");
            this.sectionJoiner();
            this.horizontalScroller();
          },
          "(max-width: 1023px)": () => {
            $(widgetContainer).removeClass("bdt-ep-hc-active");
          },
        });
      }
    }

    elementorFrontend.hooks.addAction(
      "frontend/element_ready/bdt-horizontal-scroller.default",
      function ($scope) {
        elementorFrontend.elementsHandler.addHandler(HorizontalScroller, {
          $element: $scope,
        });
      }
    );
  });
})(jQuery, window.elementorFrontend);
