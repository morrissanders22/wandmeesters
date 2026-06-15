// Common js for review card, review card carousel, review card grid, testimonial carousel, testimonial grid
(function ($, elementor) {
    "use strict";
    $(window).on("elementor/frontend/init", function () {
        /** Read more */
        const readMoreWidgetHandler = function readMoreWidgetHandler($scope) {
            if (jQuery($scope).find(".bdt-ep-read-more-text").length) {
                jQuery($scope)
                    .find(".bdt-ep-read-more-text")
                    .each(function () {
                        var words_limit_settings = $(this).data("read-more");
                        var max_words = words_limit_settings.words_length || 20; // Set the maximum number of words to show
                        var content = $(this).html(); // Get the full content
                        var cleanContent = content.replace(/<\/?[^>]+(>|$)/g, ""); // Removes all HTML tags
                        var words = cleanContent.split(/\s+/);

                        if (words.length > max_words) {
                            var short_content = words.slice(0, max_words).join(" "); // Get the first part of the content
                            var long_content = words.slice(max_words).join(" "); // Get the remaining part of the content

                            $(this).html(`
                          ${short_content}
                          <a href="#" class="bdt_read_more">...${ElementPackConfig.words_limit.read_more}</a>
                          <span class="bdt_more_text" style="display:none;">${long_content}</span>
                          <a href="#" class="bdt_read_less" style="display:none;">${ElementPackConfig.words_limit.read_less}</a>
                      `);

                            $(this)
                                .find("a.bdt_read_more")
                                .click(function (event) {
                                    event.preventDefault();
                                    $(this).hide(); // Hide the read more link
                                    $(this).siblings(".bdt_more_text").show(); // Show the more text
                                    $(this).siblings("a.bdt_read_less").show(); // Show the read less link
                                });

                            $(this)
                                .find("a.bdt_read_less")
                                .click(function (event) {
                                    event.preventDefault();
                                    $(this).hide(); // Hide the read less link
                                    $(this).siblings(".bdt_more_text").hide(); // Hide the more text
                                    $(this).siblings("a.bdt_read_more").show(); // Show the read more link
                                });
                        }
                    });
            }
        };

        const readMoreWidgetsHanlders = {
            "bdt-review-card.default": readMoreWidgetHandler,
            "bdt-review-card-carousel.default": readMoreWidgetHandler,
            "bdt-review-card-grid.default": readMoreWidgetHandler,
            "bdt-testimonial-carousel.default": readMoreWidgetHandler,
            "bdt-testimonial-carousel.bdt-twyla": readMoreWidgetHandler,
            "bdt-testimonial-carousel.bdt-vyxo": readMoreWidgetHandler,
            "bdt-testimonial-grid.default": readMoreWidgetHandler,
            "bdt-testimonial-slider.default": readMoreWidgetHandler,
            "bdt-testimonial-slider.bdt-single": readMoreWidgetHandler,
            "bdt-testimonial-slider.bdt-thumb": readMoreWidgetHandler,
        };

        $.each(readMoreWidgetsHanlders, function (widgetName, handlerFn) {
            elementorFrontend.hooks.addAction(
                "frontend/element_ready/" + widgetName,
                handlerFn
            );
        });
        /** /Read more */
    });
})(jQuery, window.elementorFrontend);

// end
