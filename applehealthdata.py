# -*- coding: utf-8 -*-
"""
applehealthdata.py: Extract data from Apple Health App's export.xml.

Copyright (c) 2016 Nicholas J. Radcliffe
Licence: MIT
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import re
import sys

from xml.etree import ElementTree
from collections import Counter, OrderedDict
from datetime import datetime

__version__ = '1.3'

HEIGHT_IN_CM = 160

RECORD_FIELDS = OrderedDict((
    # ('sourceName', 's'),
    # ('sourceVersion', 's'),
    # ('device', 's'),
    ('type', 's'),
    # ('unit', 's'),
    # ('creationDate', 'd'),
    ('startDate', 'd'),
    ('endDate', 'd'),
    ('value', 'n'),
))

ACTIVITY_SUMMARY_FIELDS = OrderedDict((
    ('dateComponents', 'd'),
    ('activeEnergyBurned', 'n'),
    ('activeEnergyBurnedGoal', 'n'),
    ('activeEnergyBurnedUnit', 's'),
    ('appleExerciseTime', 's'),
    ('appleExerciseTimeGoal', 's'),
    ('appleStandHours', 'n'),
    ('appleStandHoursGoal', 'n'),
))

WORKOUT_FIELDS = OrderedDict((
    ('sourceName', 's'),
    ('sourceVersion', 's'),
    ('device', 's'),
    ('creationDate', 'd'),
    ('startDate', 'd'),
    ('endDate', 'd'),
    ('workoutActivityType', 's'),
    ('duration', 'n'),
    ('durationUnit', 's'),
    ('totalDistance', 'n'),
    ('totalDistanceUnit', 's'),
    ('totalEnergyBurned', 'n'),
    ('totalEnergyBurnedUnit', 's'),
))

FIELDS = {
    'Record': RECORD_FIELDS,
    'ActivitySummary': ACTIVITY_SUMMARY_FIELDS,
    'Workout': WORKOUT_FIELDS,
}


RECORDS=[
    'BodyMass',
    'BodyMassIndex',
    'DistanceWalkingRunning',
    'StepCount',
    'ActiveEnergyBurned',
    'FlightsClimbed'
]

special_types = {'BodyMass', 'BodyMassIndex'}

PREFIX_RE = re.compile('^HK.*TypeIdentifier(.+)$')
ABBREVIATE = True
VERBOSE = True

def format_freqs(counter):
    """
    Format a counter object for display.
    """
    return '\n'.join('%s: %d' % (tag, counter[tag])
                     for tag in sorted(counter.keys()))


def format_value(value, datatype):
    """
    Format a value for a CSV file, escaping double quotes and backslashes.

    None maps to empty.

    datatype should be
        's' for string (escaped)
        'n' for number
        'd' for datetime
    """
    if value is None:
        return ''
    elif datatype == 's':  # string
        return '"%s"' % value.replace('\\', '\\\\').replace('"', '\\"')
    elif datatype in ('n', 'd'):  # number or date
        return value
    else:
        raise KeyError('Unexpected format value: %s' % datatype)


def abbreviate(s, enabled=ABBREVIATE):
    """
    Abbreviate particularly verbose strings based on a regular expression
    """
    m = re.match(PREFIX_RE, s)
    return m.group(1) if enabled and m else s


def encode(s):
    """
    Encode string for writing to file.
    In Python 2, this encodes as UTF-8, whereas in Python 3,
    it does nothing
    """
    return s.encode('UTF-8') if sys.version_info.major < 3 else s



class HealthDataExtractor(object):
    """
    Extract health data from Apple Health App's XML export, export.xml.

    Inputs:
        path:      Relative or absolute path to export.xml
        verbose:   Set to False for less verbose output

    Outputs:
        Writes a CSV file for each record type found, in the same
        directory as the input export.xml. Reports each file written
        unless verbose has been set to False.
    """
    def __init__(self, path, verbose=VERBOSE):
        self.in_path = path
        self.verbose = verbose
        self.directory = os.path.abspath(os.path.split(path)[0])
        with open(path) as f:
            self.report('Reading data from %s . . . ' % path, end='')
            self.data = ElementTree.parse(f)
            self.report('done')
        self.root = self.data._root
        self.nodes = list(self.root)
        self.n_nodes = len(self.nodes)
        self.abbreviate_types()
        self.collect_stats()

    def report(self, msg, end='\n'):
        if self.verbose:
            print(msg, end=end)
            sys.stdout.flush()

    def count_tags_and_fields(self):
        self.tags = Counter()
        self.fields = Counter()
        for record in self.nodes:
            self.tags[record.tag] += 1
            for k in record.keys():
                self.fields[k] += 1

    def count_record_types(self):
        """
        Counts occurrences of each type of (conceptual) "record" in the data.

        In the case of nodes of type 'Record', this counts the number of
        occurrences of each 'type' or record in self.record_types.

        In the case of nodes of type 'ActivitySummary' and 'Workout',
        it just counts those in self.other_types.

        The slightly different handling reflects the fact that 'Record'
        nodes come in a variety of different subtypes that we want to write
        to different data files, whereas (for now) we are going to write
        all Workout entries to a single file, and all ActivitySummary
        entries to another single file.
        """
        self.record_types = Counter()
        self.other_types = Counter()
        for record in self.nodes:
            if record.tag == 'Record':
                if record.attrib['type'] in RECORDS:
                    self.record_types[record.attrib['type']] += 1
                else:
                    pass
            elif record.tag in ('ActivitySummary', 'Workout'):
                self.other_types[record.tag] += 1
            elif record.tag in ('Export','ExportDate', 'Me'):
                pass
            else:
                self.report('Unexpected node of type %s.' % record.tag)
        print(self.record_types)

    def collect_stats(self):
        self.count_record_types()
        self.count_tags_and_fields()

    def open_for_writing(self):
        self.handles = {}
        self.paths = []
        for kind in (list(self.record_types) + list(self.other_types)):
            path = os.path.join(self.directory, '%s.csv' % abbreviate(kind))
            f = open(path, 'w')
            headerType = (kind if kind in ('Workout', 'ActivitySummary')
                               else 'Record')
            f.write(','.join(FIELDS[headerType].keys()) + '\n')
            self.handles[kind] = f
            self.report('Opening %s for writing' % path)

    def abbreviate_types(self):
        """
        Shorten types by removing common boilerplate text.
        """
        for node in self.nodes:
            if node.tag == 'Record':
                if 'type' in node.attrib:
                    node.attrib['type'] = abbreviate(node.attrib['type'])

    def write_records(self):
        kinds = FIELDS.keys()
        for node in self.nodes:
            if node.tag in kinds:
                attributes = node.attrib
                kind = attributes['type'] if node.tag == 'Record' else node.tag
                values = [format_value(attributes.get(field), datatype)
                          for (field, datatype) in FIELDS[node.tag].items()]
                line = encode(','.join(values) + '\n')
                if kind in RECORDS:
                    self.handles[kind].write(line)

    def close_files(self):
        for (kind, f) in self.handles.items():
            f.close()
            self.report('Written %s data.' % abbreviate(kind))

    def extract(self):
        self.open_for_writing()
        self.write_records()
        self.close_files()

    def report_stats(self):
        print('\nTags:\n%s\n' % format_freqs(self.tags))
        print('Fields:\n%s\n' % format_freqs(self.fields))
        print('Record types:\n%s\n' % format_freqs(self.record_types))

    def format_date(self, date_str):
        """
        Format the startDate for a CSV file, YYYY-MM-DD.
        """
        for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S %z'):
            try:
                return datetime.strptime(date_str, fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        raise ValueError(f"Date format not supported: {date_str}")

    def aggregate_records(self):
        """
        Aggregate records by date and type, summing the values.
        """
        aggregated_data = {}
        for node in self.nodes:
            if node.tag == 'Record' and node.attrib['type'] in RECORDS:
                type_key = node.attrib['type']
                value = float(node.attrib['value'])
                start_date = datetime.strptime(node.attrib['startDate'], '%Y-%m-%d %H:%M:%S %z')
                end_date = datetime.strptime(node.attrib['endDate'], '%Y-%m-%d %H:%M:%S %z')
                time = (end_date - start_date).total_seconds()

                if type_key in special_types:
                    date = start_date.strftime('%Y-%m-%d %H:%M:%S')
                    if type_key not in aggregated_data:
                        aggregated_data[type_key] = {}
                    if date not in aggregated_data[type_key]:
                        aggregated_data[type_key][date] = {}
                    aggregated_data[type_key][date]['value'] = value
                    aggregated_data[type_key][date]['time'] = time
                else:    
                    date = start_date.strftime('%Y-%m-%d')
                    if type_key not in aggregated_data:
                        aggregated_data[type_key] = {}
                    if date not in aggregated_data[type_key]:
                        aggregated_data[type_key][date] = {'value': 0, 'time': 0}
                    aggregated_data[type_key][date]['value'] += value
                    aggregated_data[type_key][date]['time'] += time
        return aggregated_data

    def write_aggregated_records(self, aggregated_data):
        """
        Write aggregated records to CSV files, sorted by date.
        """
        for record_type, dates_values in aggregated_data.items():
            path = os.path.join(self.directory, f'{record_type}.csv')
            with open(path, 'w') as f:
                header = ['startDate', 'value', 'time']
                f.write(','.join(header) + '\n')
                # 按照日期升序排列
                for date in sorted(dates_values.keys()):
                    total_value = round(dates_values[date]['value'],1)
                    total_time = dates_values[date]['time']
                    line = ','.join([date, str(total_value), str(total_time)])
                    f.write(line + '\n')
                self.report(f'Written aggregated data for {record_type}.')

    def extract2(self):
        aggregated_data = self.aggregate_records()
        self.write_aggregated_records(aggregated_data)

    def merge_body_mass_index(self):
        """
        Merge BodyMassIndex.csv and BodyMass.csv into a new file with startDate, weight, and bmi.
        """
        body_mass_data = {}
        body_mass_index_data = {}
        merged_data = {}

        # Read BodyMass.csv
        body_mass_path = os.path.join(self.directory, 'BodyMass.csv')
        with open(body_mass_path, 'r') as f:
            next(f)  # Skip the header line
            for line in f:
                date, weight = line.strip().split(',')[0:2]
                body_mass_data[date] = float(weight)  

        # Read BodyMassIndex.csv
        body_mass_index_path = os.path.join(self.directory, 'BodyMassIndex.csv')
        with open(body_mass_index_path, 'r') as f:
            next(f)  # Skip the header line
            for line in f:
                date, bmi = line.strip().split(',')[0:2]
                body_mass_index_data[date] = bmi

        # Merge data
        for date in sorted(set(body_mass_data.keys()) | set(body_mass_index_data.keys())):
            weight = body_mass_data.get(date, None)
            bmi = body_mass_index_data.get(date, None)
            if weight is not None:
                if bmi is None:
                    # Calculate bmi if it's None
                    bmi = round((weight * 10000 / (HEIGHT_IN_CM * HEIGHT_IN_CM)), 1)
                merged_data[date] = (weight, bmi)

        # Write merged data to new CSV file
        merged_path = os.path.join(self.directory, 'weight.csv')
        with open(merged_path, 'w') as f:
            f.write('startDate,weight,bmi\n')
            for date, (weight, bmi) in merged_data.items():
                f.write(f'{date},{weight},{bmi}\n')

    def merge_step_calories_walking_flights(self):
        step_data = {}
        calories_data = {}
        distance_data = {}
        active_time_data = {}
        merged_data = {}

        step_count_path = os.path.join(self.directory, 'StepCount.csv')
        with open(step_count_path, 'r') as f:
            next(f)  # Skip the header line
            for line in f:
                date, step = line.strip().split(',')[0:2]
                step_data[date] = step 

        # Read ActiveEnergyBurned.csv
        calories_path = os.path.join(self.directory, 'ActiveEnergyBurned.csv')
        with open(calories_path, 'r') as f:
            next(f)  # Skip the header line
            for line in f:
                date, calories = line.strip().split(',')[0:2]
                calories_data[date] = round(float(calories),1)

        # Read DistanceWalkingRunning.csv
        distance_path = os.path.join(self.directory, 'DistanceWalkingRunning.csv')
        with open(distance_path, 'r') as f:
            next(f)  # Skip the header line
            for line in f:
                date, distance = line.strip().split(',')[0:2]
                distance_data[date] = round(float(distance),2)

        # Read DistanceWalkingRunning.csv
        # active_time_path = os.path.join(self.directory, 'DistanceWalkingRunning.csv')
        # with open(active_time_path, 'r') as f:
        #     next(f)  # Skip the header line
        #     for line in f:
        #         date, active_time = line.strip().split(',')[0:2]
        #         active_time_data[date] = active_time

        # Merge data
        for date in sorted(set(step_data.keys())):
            step = step_data.get(date, None)
            calories = calories_data.get(date, None)
            distance = distance_data.get(date, None)
            if step is not None:
                merged_data[date] = (step, calories, distance)

        # Write merged data to new CSV file
        merged_path = os.path.join(self.directory, 'step.csv')
        with open(merged_path, 'w') as f:
            f.write('Date,taSource,Steps,Calories,Distance(km),ActiveTime(seconds)\n')
            for date, (step, calories, distance) in merged_data.items():
                f.write(f'{date},{step},{calories},{distance}\n')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('USAGE: python3 applehealthdata.py /path/to/export.xml',
              file=sys.stderr)
        sys.exit(1)
    data = HealthDataExtractor(sys.argv[1])
    data.report_stats()
    data.extract2()
    # data.merge_body_mass_index()
    # data.merge_step_calories_walking_flights()
