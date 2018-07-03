/** 
 * jQuery.autocomplete
 * 
 * @param config {Object}
 * @example <code>
  $('#search [name=query]').autocomplete({ 
    url: '/search/suggest',
    list_container: '#suggestions',
    template: '<li>suggestion</li>'
  });
 * </code>
 */
$.fn.autocomplete = function(config){ return this.each(function(){
    var searching, query,

        name = $(this).attr('name'),

        select_item = function(event) {
          var item = $(event.target).closest('li');

          $('.current').add(item).toggleClass('current');
          list_container.trigger('hide');
          input.val(item.text());
        },
        
        hide_list = function(event){
          $(this).removeClass('open').empty();
        },
    
        // list container events
        list_container = $(config.list_container)
          .on('select', select_item)
          .on('hide', hide_list),

        // input events  
        input = $(this)
          .attr('autocomplete', 'off')
          .click(function(){ return false })
          .keyup(function(event){
            clearTimeout(searching);
            switch (event.keyCode) {
            case 38: // UP
              $('.current', list_container).prev()
                .add('li:last-child', list_container)
                .first()
                  .trigger('select');
              break;
            case 40: // DOWN
              $('.current', list_container).next()
                .add('li:first-child', list_container)
                .last()
                  .trigger('select');
              break;
            case 27: // ESC
              input.val(query);
              $('.current', list_container.trigger('hide'))
                .removeClass('current');
              break;
            case 39: // RIGHT
            case 37: // LEFT
              break;
            default:
              searching = setTimeout(function(){
                var term = input.val();
                if (!term) return list_container.trigger('hide');
                if (query == term) return;
                
                query = term;
                $.getJSON(config.url, input.serialize())
                  .then(function(response){
                    list_container.trigger('hide');

                    if(config.map) {
                        response.suggestions = config.map(response.suggestions);
                    }

                    $.each(response.suggestions || {}, function(n, suggestion) {
                      $(config.template.replace('TITLE', suggestion.title))
                        .hover(function(){ $('.current', list_container).removeClass('current'); })
                        .click(select_item)
                        .appendTo(list_container.addClass('open'));
                    });
                  });
              }, config.delay || 250);
            break;
            }
          });
});};
