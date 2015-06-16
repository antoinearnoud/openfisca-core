# -*- coding: utf-8 -*-


# OpenFisca -- A versatile microsimulation software
# By: OpenFisca Team <contact@openfisca.fr>
#
# Copyright (C) 2011, 2012, 2013, 2014, 2015 OpenFisca Team
# https://github.com/openfisca
#
# This file is part of OpenFisca.
#
# OpenFisca is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# OpenFisca is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


"""Handle legislative parameters in XML format (and convert then to JSON)."""


import collections
import datetime
import logging
import itertools

import xml.etree.ElementTree

from . import conv


# legislation_json_key_by_xml_tag = dict(
#    ASSIETTE = 'base',  # "base" is singular, because a bracket has only one base.
#    BAREME = 'scales',
#    CODE = 'parameters',
#    MONTANT = 'amount',
#    NODE = 'nodes',
#    SEUIL= 'threshold',  # "threshold" is singular, because a bracket has only one base.
#    TAUX = 'rate',  # "rate" is singular, because a bracket has only one base.
#    TRANCHE = 'brackets', # TODO: should be renamed to bracket
#    VALUE = 'values',
#    )

default_format = 'float'
log = logging.getLogger(__name__)
json_unit_by_xml_json_type = dict(
    age = u'year',
    days = u'day',
    hours = u'hour',
    monetary = u'currency',
    months = u'month',
    )
xml_json_formats = (
    'bool',
    'float',
    'integer',
    'percent',
    )


# Helper functions

def N_(message):
    return message


# Level 1 converters

def make_validate_values_xml_json_dates(require_consecutive_dates = False):
    def validate_values_xml_json_dates(values_xml_json, state = None):
        if not values_xml_json:
            return values_xml_json, None
        if state is None:
            state = conv.default_state

        errors = {}
        for index, value_xml_json in enumerate(values_xml_json):
            if value_xml_json['deb'] > value_xml_json['fin']:
                errors[index] = dict(fin = state._(u"Last date must be greater than first date"))

        sorted_values_xml_json = sorted(values_xml_json, key = lambda value_xml_json: value_xml_json['deb'],
            reverse = True)
        next_value_xml_json = sorted_values_xml_json[0]
        for index, value_xml_json in enumerate(itertools.islice(sorted_values_xml_json, 1, None)):
            next_date_str = (datetime.date(*(int(fragment) for fragment in value_xml_json['fin'].split('-'))) +
                datetime.timedelta(days = 1)).isoformat()
            if require_consecutive_dates and next_date_str < next_value_xml_json['deb']:
                errors.setdefault(index, {})['deb'] = state._(u"Dates of values are not consecutive")
            elif next_date_str > next_value_xml_json['deb']:
                errors.setdefault(index, {})['deb'] = state._(u"Dates of values overlap")
            next_value_xml_json = value_xml_json

        return sorted_values_xml_json, errors or None

    return validate_values_xml_json_dates


def translate_xml_element_to_json_item(xml_element):
    json_element = collections.OrderedDict()
    text = xml_element.text
    if text is not None:
        text = text.strip().strip('#').strip() or None
        if text is not None:
            json_element['text'] = text
    start_line_number = getattr(xml_element, "start_line_number", None)
    end_line_number = getattr(xml_element, "end_line_number", None)
    if start_line_number is not None:
        json_element['start_line_number'] = start_line_number
    if end_line_number is not None and end_line_number != start_line_number:
        json_element['end_line_number'] = end_line_number
    json_element.update(xml_element.attrib)
    for xml_child in xml_element:
        json_child_key, json_child = translate_xml_element_to_json_item(xml_child)
        json_element.setdefault(json_child_key, []).append(json_child)
    tail = xml_element.tail
    if tail is not None:
        tail = tail.strip().strip('#').strip() or None
        if tail is not None:
            json_element['tail'] = tail
    return xml_element.tag, json_element


def transform_node_xml_json_to_json(node_xml_json, root = True):
    comments = []
    node_json = collections.OrderedDict()
    if root:
        node_json['@context'] = u'http://openfisca.fr/contexts/legislation.jsonld'
    node_json['@type'] = 'Node'
    child_json_by_code = {}
    for key, value in node_xml_json.iteritems():
        if key == 'BAREME':
            for child_xml_json in value:
                child_code, child_json = transform_scale_xml_json_to_json(child_xml_json)
                child_json_by_code[child_code] = child_json
        elif key == 'CODE':
            for child_xml_json in value:
                child_code, child_json = transform_parameter_xml_json_to_json(child_xml_json)
                child_json_by_code[child_code] = child_json
        elif key == 'code':
            pass
        elif key == 'deb':
            node_json['start'] = value
        elif key == 'fin':
            node_json['stop'] = value
        elif key == 'NODE':
            for child_xml_json in value:
                child_code, child_json = transform_node_xml_json_to_json(child_xml_json, root = False)
                child_json_by_code[child_code] = child_json
        elif key in ('tail', 'text'):
            comments.append(value)
        else:
            node_json[key] = value
    node_json['children'] = collections.OrderedDict(sorted(child_json_by_code.iteritems()))
    if comments:
        node_json['comment'] = u'\n\n'.join(comments)
    return node_xml_json['code'], node_json


def transform_parameter_xml_json_to_json(parameter_xml_json):
    comments = []
    parameter_json = collections.OrderedDict()
    parameter_json['@type'] = 'Parameter'
    xml_json_value_to_json_transformer = float
    for key, value in parameter_xml_json.iteritems():
        if key in ('code', 'taille'):
            pass
        elif key == 'format':
            parameter_json[key] = dict(
                bool = u'boolean',
                percent = u'rate',
                ).get(value, value)
            if value == 'bool':
                xml_json_value_to_json_transformer = lambda xml_json_value: bool(int(xml_json_value))
            elif value == 'integer':
                xml_json_value_to_json_transformer = int
        elif key in ('tail', 'text'):
            comments.append(value)
        elif key == 'type':
            parameter_json['unit'] = json_unit_by_xml_json_type.get(value, value)
        elif key == 'VALUE':
            parameter_json['values'] = [
                transform_value_xml_json_to_json(item, xml_json_value_to_json_transformer)
                for item in value
                ]
        else:
            parameter_json[key] = value
    if parameter_json.get('format') is None:
        parameter_json['format'] = default_format
    if comments:
        parameter_json['comment'] = u'\n\n'.join(comments)
    return parameter_xml_json['code'], parameter_json


def transform_scale_xml_json_to_json(scale_xml_json):
    comments = []
    scale_json = collections.OrderedDict()
    scale_json['@type'] = 'Scale'
    for key, value in scale_xml_json.iteritems():
        if key == 'code':
            pass
        elif key in ('tail', 'text'):
            comments.append(value)
        elif key == 'TRANCHE':
            scale_json['brackets'] = [
                transform_bracket_xml_json_to_json(item)
                for item in value
                ]
        elif key == 'type':
            scale_json['unit'] = json_unit_by_xml_json_type.get(value, value)
        else:
            scale_json[key] = value
    if comments:
        scale_json['comment'] = u'\n\n'.join(comments)
    return scale_xml_json['code'], scale_json


def transform_bracket_xml_json_to_json(bracket_xml_json):
    comments = []
    bracket_json = collections.OrderedDict()
    for key, value in bracket_xml_json.iteritems():
        if key == 'ASSIETTE':
            bracket_json['base'] = transform_values_holder_xml_json_to_json(value[0])
        elif key == 'code':
            pass
        elif key == 'MONTANT':
            bracket_json['amount'] = transform_values_holder_xml_json_to_json(value[0])
        elif key == 'SEUIL':
            bracket_json['threshold'] = transform_values_holder_xml_json_to_json(value[0])
        elif key in ('tail', 'text'):
            comments.append(value)
        elif key == 'TAUX':
            bracket_json['rate'] = transform_values_holder_xml_json_to_json(value[0])

        else:
            bracket_json[key] = value
    if comments:
        bracket_json['comment'] = u'\n\n'.join(comments)
    return bracket_json


def transform_value_xml_json_to_json(value_xml_json, xml_json_value_to_json_transformer):
    comments = []
    value_json = collections.OrderedDict()
    for key, value in value_xml_json.iteritems():
        assert key not in ('code', 'format', 'type')
        if key == 'deb':
            value_json['start'] = value
        elif key == 'fin':
            value_json['stop'] = value
        elif key in ('tail', 'text'):
            comments.append(value)
        elif key == 'valeur':
            try:
                value_json['value'] = xml_json_value_to_json_transformer(value)
            except TypeError:
                log.error(u'Invalid value: {}'.format(value))
                raise
        else:
            value_json[key] = value
    if comments:
        value_json['comment'] = u'\n\n'.join(comments)
    return value_json


def transform_values_holder_xml_json_to_json(values_holder_xml_json):
    return [
        transform_value_xml_json_to_json(item, float)
        for item in values_holder_xml_json['VALUE']
        ]


def validate_legislation_xml_json(legislation, state = None):
    if legislation is None:
        return None, None
    if state is None:
        state = conv.default_state

    legislation, error = conv.pipe(
        conv.test_isinstance(dict),
        conv.struct(
            dict(
                deb = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.iso8601_input_to_date,
                    conv.date_to_iso8601_str,
                    conv.not_none,
                    ),
                fin = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.iso8601_input_to_date,
                    conv.date_to_iso8601_str,
                    conv.not_none,
                    ),
                ),
            constructor = collections.OrderedDict,
            default = conv.noop,
            drop_none_values = 'missing',
            keep_value_order = True,
            ),
        )(legislation, state = state)
    if error is not None:
        return legislation, error

    deb = legislation.pop('deb')
    fin = legislation.pop('fin')
    legislation, error = validate_node_xml_json(legislation, state = state)
    legislation['deb'] = deb
    legislation['fin'] = fin
    return legislation, error


def validate_node_xml_json(node, state = None):
    if node is None:
        return None, None
    state = conv.add_ancestor_to_state(state, node)
    validated_node, errors = conv.pipe(
        conv.test_isinstance(dict),
        conv.struct(
            dict(
                BAREME = conv.pipe(
                    conv.test_isinstance(list),
                    conv.uniform_sequence(
                        validate_scale_xml_json,
                        drop_none_items = True,
                        ),
                    conv.empty_to_none,
                    ),
                CODE = conv.pipe(
                    conv.test_isinstance(list),
                    conv.uniform_sequence(
                        validate_parameter_xml_json,
                        drop_none_items = True,
                        ),
                    conv.empty_to_none,
                    ),
                code = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_line,
                    conv.not_none,
                    ),
                description = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_line,
                    ),
                end_line_number = conv.test_isinstance(int),
                NODE = conv.pipe(
                    conv.test_isinstance(list),
                    conv.uniform_sequence(
                        validate_node_xml_json,
                        drop_none_items = True,
                        ),
                    conv.empty_to_none,
                    ),
                start_line_number = conv.test_isinstance(int),
                tail = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                text = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                ),
            constructor = collections.OrderedDict,
            drop_none_values = 'missing',
            keep_value_order = True,
            ),
        )(node, state = state)
    if errors is None:
        children_groups_key = ('BAREME', 'CODE', 'NODE')
        if all(
                validated_node.get(key) is None
                for key in children_groups_key
                ):
            error = state._(u"At least one of the following items must be present: {}").format(state._(u', ').join(
                u'"{}"'.format(key)
                for key in children_groups_key
                ))
            errors = dict(
                (key, error)
                for key in children_groups_key
                )
        else:
            errors = {}
        children_code = set()
        for key in children_groups_key:
            for child_index, child in enumerate(validated_node.get(key) or []):
                child_code = child['code']
                if child_code in children_code:
                    errors.setdefault(key, {}).setdefault(child_index, {})['code'] = state._(u"Duplicate value")
                else:
                    children_code.add(child_code)
    conv.remove_ancestor_from_state(state, node)
    return validated_node, errors or None


def validate_parameter_xml_json(parameter, state = None):
    if parameter is None:
        return None, None
    state = conv.add_ancestor_to_state(state, parameter)
    validated_parameter, errors = conv.pipe(
        conv.test_isinstance(dict),
        conv.struct(
            dict(
                code = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_line,
                    conv.not_none,
                    ),
                description = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_line,
                    ),
                end_line_number = conv.test_isinstance(int),
                format = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.input_to_slug,
                    conv.test_in(xml_json_formats),
                    ),
                start_line_number = conv.test_isinstance(int),
                tail = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                taille = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.test_in([
                        'moinsde20',
                        'plusde20',
                        ]),
                    ),
                text = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                type = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.input_to_slug,
                    conv.test_in(json_unit_by_xml_json_type),
                    ),
                VALUE = conv.pipe(
                    conv.test_isinstance(list),
                    conv.uniform_sequence(
                        validate_value_xml_json,
                        drop_none_items = True,
                        ),
                    make_validate_values_xml_json_dates(require_consecutive_dates = True),
                    conv.empty_to_none,
                    conv.not_none,
                    ),
                ),
            constructor = collections.OrderedDict,
            drop_none_values = 'missing',
            keep_value_order = True,
            ),
        )(parameter, state = state)
    conv.remove_ancestor_from_state(state, parameter)
    return validated_parameter, errors


def validate_scale_xml_json(scale, state = None):
    if scale is None:
        return None, None
    state = conv.add_ancestor_to_state(state, scale)
    validated_scale, errors = conv.pipe(
        conv.test_isinstance(dict),
        conv.struct(
            dict(
                code = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_line,
                    conv.not_none,
                    ),
                description = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_line,
                    ),
                end_line_number = conv.test_isinstance(int),
                option = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.input_to_slug,
                    conv.test_in((
                        'contrib',
                        'main-d-oeuvre',
                        'noncontrib',
                        )),
                    ),
                start_line_number = conv.test_isinstance(int),
                TRANCHE = conv.pipe(
                    conv.test_isinstance(list),
                    conv.uniform_sequence(
                        validate_bracket_xml_json,
                        drop_none_items = True,
                        ),
                    validate_brackets_xml_json_types,
                    validate_brackets_xml_json_dates,
                    conv.empty_to_none,
                    conv.not_none,
                    ),
                tail = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                text = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                type = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.input_to_slug,
                    conv.test_in((
                        'monetary',
                        )),
                    ),
                ),
            constructor = collections.OrderedDict,
            drop_none_values = 'missing',
            keep_value_order = True,
            ),
        )(scale, state = state)
    conv.remove_ancestor_from_state(state, scale)
    return validated_scale, errors


def validate_bracket_xml_json(bracket, state = None):
    if bracket is None:
        return None, None
    state = conv.add_ancestor_to_state(state, bracket)
    validated_bracket, errors = conv.pipe(
        conv.test_isinstance(dict),
        conv.struct(
            dict(
                ASSIETTE = conv.pipe(
                    conv.test_isinstance(list),
                    conv.uniform_sequence(
                        validate_values_holder_xml_json,
                        drop_none_items = True,
                        ),
                    conv.empty_to_none,
                    conv.test(lambda l: len(l) == 1, error = N_(u"List must contain one and only one item")),
                    ),
                code = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_line,
                    ),
                end_line_number = conv.test_isinstance(int),
                MONTANT = conv.pipe(
                    conv.test_isinstance(list),
                    conv.uniform_sequence(
                        validate_values_holder_xml_json,
                        drop_none_items = True,
                        ),
                    conv.empty_to_none,
                    conv.test(lambda l: len(l) == 1, error = N_(u"List must contain one and only one item")),
                    ),
                SEUIL = conv.pipe(
                    conv.test_isinstance(list),
                    conv.uniform_sequence(
                        validate_values_holder_xml_json,
                        drop_none_items = True,
                        ),
                    conv.empty_to_none,
                    conv.test(lambda l: len(l) == 1, error = N_(u"List must contain one and only one item")),
                    conv.not_none,
                    ),
                start_line_number = conv.test_isinstance(int),
                tail = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                TAUX = conv.pipe(
                    conv.test_isinstance(list),
                    conv.uniform_sequence(
                        validate_values_holder_xml_json,
                        drop_none_items = True,
                        ),
                    conv.empty_to_none,
                    conv.test(lambda l: len(l) == 1, error = N_(u"List must contain one and only one item")),
                    ),
                text = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                ),
            constructor = collections.OrderedDict,
            drop_none_values = 'missing',
            keep_value_order = True,
            ),
        conv.test(lambda bracket: bool(bracket.get('MONTANT')) ^ bool(bracket.get('TAUX')),
            error = N_(u"Either MONTANT or TAUX must be provided")),
        )(bracket, state = state)
    conv.remove_ancestor_from_state(state, bracket)
    return validated_bracket, errors


def validate_brackets_xml_json_dates(brackets, state = None):
    if not brackets:
        return brackets, None
    if state is None:
        state = conv.default_state
    errors = {}

    previous_bracket = brackets[0]
    for bracket_index, bracket in enumerate(itertools.islice(brackets, 1, None), 1):
        for key in ('ASSIETTE', 'MONTANT', 'SEUIL', 'TAUX'):
            valid_segments = []
            values_holder_xml_json = previous_bracket.get(key)
            values_xml_json = values_holder_xml_json[0]['VALUE'] if values_holder_xml_json else []
            for value_xml_json in values_xml_json:
                from_date = datetime.date(*(int(fragment) for fragment in value_xml_json['deb'].split('-')))
                to_date = datetime.date(*(int(fragment) for fragment in value_xml_json['fin'].split('-')))
                if valid_segments and valid_segments[-1][0] == to_date + datetime.timedelta(days = 1):
                    valid_segments[-1] = (from_date, valid_segments[-1][1])
                else:
                    valid_segments.append((from_date, to_date))

            values_holder_xml_json = bracket.get(key)
            values_xml_json = values_holder_xml_json[0]['VALUE'] if values_holder_xml_json else []
            for value_index, value_xml_json in enumerate(values_xml_json):
                from_date = datetime.date(*(int(fragment) for fragment in value_xml_json['deb'].split('-')))
                to_date = datetime.date(*(int(fragment) for fragment in value_xml_json['fin'].split('-')))
                for valid_segment in valid_segments:
                    if valid_segment[0] <= from_date and to_date <= valid_segment[1]:
                        break
                else:
                    errors.setdefault(bracket_index, {}).setdefault(key, {}).setdefault(0, {}).setdefault('VALUE',
                        {}).setdefault(value_index, {})['deb'] = state._(
                        u"Dates don't belong to valid dates of previous bracket")
        previous_bracket = bracket
    if errors:
        return brackets, errors

    for bracket_index, bracket in enumerate(itertools.islice(brackets, 1, None), 1):
        amount_segments = []
        values_holder_xml_json = bracket.get('MONTANT')
        values_xml_json = values_holder_xml_json[0]['VALUE'] if values_holder_xml_json else []
        for value_xml_json in values_xml_json:
            from_date = datetime.date(*(int(fragment) for fragment in value_xml_json['deb'].split('-')))
            to_date = datetime.date(*(int(fragment) for fragment in value_xml_json['fin'].split('-')))
            if amount_segments and amount_segments[-1][0] == to_date + datetime.timedelta(days = 1):
                amount_segments[-1] = (from_date, amount_segments[-1][1])
            else:
                amount_segments.append((from_date, to_date))

        rate_segments = []
        values_holder_xml_json = bracket.get('TAUX')
        values_xml_json = values_holder_xml_json[0]['VALUE'] if values_holder_xml_json else []
        for value_xml_json in values_xml_json:
            from_date = datetime.date(*(int(fragment) for fragment in value_xml_json['deb'].split('-')))
            to_date = datetime.date(*(int(fragment) for fragment in value_xml_json['fin'].split('-')))
            if rate_segments and rate_segments[-1][0] == to_date + datetime.timedelta(days = 1):
                rate_segments[-1] = (from_date, rate_segments[-1][1])
            else:
                rate_segments.append((from_date, to_date))

        threshold_segments = []
        values_holder_xml_json = bracket.get('SEUIL')
        values_xml_json = values_holder_xml_json[0]['VALUE'] if values_holder_xml_json else []
        for value_xml_json in values_xml_json:
            from_date = datetime.date(*(int(fragment) for fragment in value_xml_json['deb'].split('-')))
            to_date = datetime.date(*(int(fragment) for fragment in value_xml_json['fin'].split('-')))
            if threshold_segments and threshold_segments[-1][0] == to_date + datetime.timedelta(days = 1):
                threshold_segments[-1] = (from_date, threshold_segments[-1][1])
            else:
                threshold_segments.append((from_date, to_date))

        values_holder_xml_json = bracket.get('ASSIETTE')
        values_xml_json = values_holder_xml_json[0]['VALUE'] if values_holder_xml_json else []
        for value_index, value_xml_json in enumerate(values_xml_json):
            from_date = datetime.date(*(int(fragment) for fragment in value_xml_json['deb'].split('-')))
            to_date = datetime.date(*(int(fragment) for fragment in value_xml_json['fin'].split('-')))
            for rate_segment in rate_segments:
                if rate_segment[0] <= from_date and to_date <= rate_segment[1]:
                    break
            else:
                errors.setdefault(bracket_index, {}).setdefault('ASSIETTE', {}).setdefault(0, {}).setdefault('VALUE',
                    {}).setdefault(value_index, {})['deb'] = state._(u"Dates don't belong to TAUX dates")

        values_holder_xml_json = bracket.get('TAUX')
        values_xml_json = values_holder_xml_json[0]['VALUE'] if values_holder_xml_json else []
        for value_index, value_xml_json in enumerate(values_xml_json):
            from_date = datetime.date(*(int(fragment) for fragment in value_xml_json['deb'].split('-')))
            to_date = datetime.date(*(int(fragment) for fragment in value_xml_json['fin'].split('-')))
            for threshold_segment in threshold_segments:
                if threshold_segment[0] <= from_date and to_date <= threshold_segment[1]:
                    break
            else:
                errors.setdefault(bracket_index, {}).setdefault('TAUX', {}).setdefault(0, {}).setdefault('VALUE',
                    {}).setdefault(value_index, {})['deb'] = state._(u"Dates don't belong to SEUIL dates")

        values_holder_xml_json = bracket.get('SEUIL')
        values_xml_json = values_holder_xml_json[0]['VALUE'] if values_holder_xml_json else []
        for value_index, value_xml_json in enumerate(values_xml_json):
            from_date = datetime.date(*(int(fragment) for fragment in value_xml_json['deb'].split('-')))
            to_date = datetime.date(*(int(fragment) for fragment in value_xml_json['fin'].split('-')))
            for rate_segment in rate_segments:
                if rate_segment[0] <= from_date and to_date <= rate_segment[1]:
                    break
            else:
                for amount_segment in amount_segments:
                    if amount_segment[0] <= from_date and to_date <= amount_segment[1]:
                        break
                else:
                    errors.setdefault(bracket_index, {}).setdefault('SEUIL', {}).setdefault(0, {}).setdefault('VALUE',
                        {}).setdefault(value_index, {})['deb'] = state._(u"Dates don't belong to TAUX or MONTANT dates")
    return brackets, errors or None


def validate_brackets_xml_json_types(brackets, state = None):
    if not brackets:
        return brackets, None

    has_amount = any(
        'MONTANT' in bracket
        for bracket in brackets
        )
    if has_amount:
        if state is None:
            state = conv.default_state
        errors = {}
        for bracket_index, bracket in enumerate(brackets):
            if 'ASSIETTE' in bracket:
                errors.setdefault(bracket_index, {})['ASSIETTE'] = state._(
                    u"A scale can't contain both MONTANT and ASSIETTE")
            if 'TAUX' in bracket:
                errors.setdefault(bracket_index, {})['TAUX'] = state._(u"A scale can't contain both MONTANT and TAUX")
        if errors:
            return brackets, errors
    return brackets, None


def validate_value_xml_json(value, state = None):
    if value is None:
        return None, None
    container = state.ancestors[-1]
    value_converter = dict(
        bool = conv.pipe(
            conv.test_isinstance(basestring),
            conv.cleanup_line,
            conv.test_in([u'0', u'1']),
            ),
        float = conv.pipe(
            conv.test_isinstance(basestring),
            conv.cleanup_line,
            conv.test_conv(conv.anything_to_float),
            ),
        integer = conv.pipe(
            conv.test_isinstance(basestring),
            conv.cleanup_line,
            conv.test_conv(conv.anything_to_strict_int),
            ),
        percent = conv.pipe(
            conv.test_isinstance(basestring),
            conv.cleanup_line,
            conv.test_conv(conv.anything_to_float),
            ),
        )[container.get('format') or default_format]  # Only CODE have a "format".
    state = conv.add_ancestor_to_state(state, value)
    validated_value, errors = conv.pipe(
        conv.test_isinstance(dict),
        conv.struct(
            dict(
                deb = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.iso8601_input_to_date,
                    conv.date_to_iso8601_str,
                    conv.not_none,
                    ),
                end_line_number = conv.test_isinstance(int),
                fin = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.iso8601_input_to_date,
                    conv.date_to_iso8601_str,
                    conv.not_none,
                    ),
                start_line_number = conv.test_isinstance(int),
                tail = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                text = conv.pipe(
                    conv.test_isinstance(basestring),
                    conv.cleanup_text,
                    ),
                valeur = conv.pipe(
                    value_converter,
                    conv.not_none,
                    ),
                ),
            constructor = collections.OrderedDict,
            drop_none_values = 'missing',
            keep_value_order = True,
            ),
        )(value, state = state)
    conv.remove_ancestor_from_state(state, value)
    return validated_value, errors


validate_values_holder_xml_json = conv.struct(
    dict(
        end_line_number = conv.test_isinstance(int),
        start_line_number = conv.test_isinstance(int),
        VALUE = conv.pipe(
            conv.test_isinstance(list),
            conv.uniform_sequence(
                validate_value_xml_json,
                drop_none_items = True,
                ),
            make_validate_values_xml_json_dates(require_consecutive_dates = False),
            conv.empty_to_none,
            conv.not_none,
            ),
        ),
    constructor = collections.OrderedDict,
    drop_none_values = 'missing',
    keep_value_order = True,
    )


def xml_legislation_file_path_to_xml(value, state = None):
    # From # http://bugs.python.org/issue14078#msg153907
    class XMLParserWithLineNumbers(xml.etree.ElementTree.XMLParser):
        def _end(self, *args, **kwargs):
            element = super(self.__class__, self)._end(*args, **kwargs)
            element.end_line_number = self._parser.CurrentLineNumber
            return element

        def _start_list(self, *args, **kwargs):
            element = super(self.__class__, self)._start_list(*args, **kwargs)
            element.start_line_number = self._parser.CurrentLineNumber
            return element

    parser = XMLParserWithLineNumbers()
    try:
        legislation_tree = xml.etree.ElementTree.parse(value, parser = parser)
    except xml.etree.ElementTree.ParseError as error:
        return value, unicode(error)
    xml_legislation = legislation_tree.getroot()
    return xml_legislation, None


def xml_legislation_to_json(xml_element, state = None):
    if xml_element is None:
        return None, None
    json_key, json_element = translate_xml_element_to_json_item(xml_element)
    if json_key != 'NODE':
        if state is None:
            state = conv.default_state
        return json_element, state._(u'Invalid root element in XML: "{}" instead of "NODE"').format(xml_element.tag)
    return json_element, None


# Level 2 converters

xml_legislation_file_path_to_json = conv.pipe(
    xml_legislation_file_path_to_xml,
    xml_legislation_to_json,
    validate_legislation_xml_json,
    conv.function(lambda value: transform_node_xml_json_to_json(value)[1]),
    )
