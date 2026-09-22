{#
    Deterministic surrogate key for composite-grain marts.

    dbt_utils.generate_surrogate_key does the same job, but this project deliberately ships with no
    package dependencies so `dbt build` works on a machine with no access to the dbt package hub.
#}
{% macro surrogate_key(columns) %}
    md5(
        {%- for column in columns %}
        coalesce(cast({{ column }} as varchar), '_')
        {%- if not loop.last %} || '|' || {% endif %}
        {%- endfor %}
    )
{% endmacro %}
