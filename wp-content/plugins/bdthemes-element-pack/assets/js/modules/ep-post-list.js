(function ($) {
    var categoryCache = {};

    $(window).on("elementor/frontend/init", function () {
        elementorFrontend.hooks.addAction(
            "frontend/element_ready/bdt-post-list.default",
            function (scope) {
                scope.find(".bdt-post-list-wrap").each(function () {
                    var element = $(this)[0];

                    if (element) {
                        var $settings_showHide = $(this).data("show-hide");
                        var tabs = $(this).find(".bdt-option");
                        var tabs_header = $(this).find(".bdt-post-list-header");
                        var item_wrapper = $(this).find(".bdt-post-list");
                        var loader = $(this).find("#bdt-loading-image");
                        var settings = item_wrapper.data("settings");

                        function loadCategoryData(slug) {
                            // Show the loader at the beginning of each request
                            $(loader).show();

                            if (categoryCache[slug]) {
                                item_wrapper.html(categoryCache[slug]);
                                console.log("Using cached data for category:", slug);
                                $(loader).hide();
                            } else {
                                $.ajax({
                                    url: ElementPackConfig.ajaxurl,
                                    data: {
                                        action: "bdt_post_list",
                                        nonce: ElementPackConfig.nonce,
                                        settings: settings,
                                        post_type: settings["post-type"],
                                        showHide: $settings_showHide,
                                        category: slug,
                                        human_diff_time: $settings_showHide["human_diff_time"],
                                        human_diff_time_short: $settings_showHide["human_diff_time_short"],
                                        bdt_link_new_tab: $settings_showHide["bdt_link_new_tab"],
                                    },
                                    type: "POST",
                                    dataType: "HTML",
                                    beforeSend: function() {
                                        // Ensure loader is shown in case it's hidden unexpectedly
                                        $(loader).show();
                                    },
                                    success: function (response) {
                                        categoryCache[slug] = response;
                                        item_wrapper.html(response);
                                    },
                                    error: function (response) {
                                        console.log(response);
                                    },
                                    complete: function() {
                                        // Hide the loader after the request completes
                                        $(loader).hide();
                                    },
                                });
                            }
                        }

                        tabs.on("click", function (e) {
                            var slug = $(this).data("slug");
                            tabs_header.find(".bdt-filter-list").removeClass("bdt-active");
                            $(this).parent().addClass("bdt-active");
                            e.preventDefault();
                            loadCategoryData(slug);
                        });
                        
                    }
                });
            }
        );
    });
})(jQuery);
