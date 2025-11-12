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
    'FlightsClimbed',
    'ActiveEnergyBurned',
    'HeartRate'
]

special_types = {'BodyMass', 'BodyMassIndex'}
# 需要计算平均值的类型（而不是求和）
average_types = {'HeartRate'}

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

    def abbreviate_types(self):
        """
        Shorten types by removing common boilerplate text.
        """
        for node in self.nodes:
            if node.tag == 'Record':
                if 'type' in node.attrib:
                    node.attrib['type'] = abbreviate(node.attrib['type'])

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
        For average_types (like HeartRate), calculate the average instead of sum.
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
                elif type_key in average_types:
                    # 对于需要计算平均值的类型（如心率），记录所有值和计数
                    date = start_date.strftime('%Y-%m-%d')
                    if type_key not in aggregated_data:
                        aggregated_data[type_key] = {}
                    if date not in aggregated_data[type_key]:
                        aggregated_data[type_key][date] = {'sum': 0, 'count': 0, 'time': 0}
                    aggregated_data[type_key][date]['sum'] += value
                    aggregated_data[type_key][date]['count'] += 1
                    aggregated_data[type_key][date]['time'] += time
                else:    
                    # 对于累计类型（如步数、卡路里），求和
                    date = start_date.strftime('%Y-%m-%d')
                    if type_key not in aggregated_data:
                        aggregated_data[type_key] = {}
                    if date not in aggregated_data[type_key]:
                        aggregated_data[type_key][date] = {'value': 0, 'time': 0}
                    aggregated_data[type_key][date]['value'] += value
                    aggregated_data[type_key][date]['time'] += time
        return aggregated_data


    def export_unified_csv(self):
        """
        将所有记录类型按日期聚合到一个统一的 CSV 文件中。
        对于特殊类型（BodyMass, BodyMassIndex），取当天的最后一个值。
        对于其他类型，使用已聚合的日累计值。
        """
        aggregated_data = self.aggregate_records()
        
        # 收集所有日期
        all_dates = set()
        for record_type, dates_values in aggregated_data.items():
            if record_type in special_types:
                # 对于特殊类型，将精确时间戳转换为日期
                for date_time in dates_values.keys():
                    try:
                        # 尝试解析带时间的日期格式
                        dt = datetime.strptime(date_time, '%Y-%m-%d %H:%M:%S')
                        all_dates.add(dt.strftime('%Y-%m-%d'))
                    except ValueError:
                        # 如果已经是日期格式，直接使用
                        all_dates.add(date_time)
            else:
                # 对于普通类型，日期已经是 YYYY-MM-DD 格式
                all_dates.update(dates_values.keys())
        
        # 按日期排序
        sorted_dates = sorted(all_dates)
        
        # 构建统一的数据结构
        unified_data = {}
        for date in sorted_dates:
            unified_data[date] = {}
            for record_type in RECORDS:
                unified_data[date][record_type] = None
        
        # 填充数据
        for record_type, dates_values in aggregated_data.items():
            if record_type in special_types:
                # 对于特殊类型，按日期分组，取当天的最后一个值（时间最晚的）
                date_groups = {}
                for date_time, value_data in dates_values.items():
                    try:
                        dt = datetime.strptime(date_time, '%Y-%m-%d %H:%M:%S')
                        date = dt.strftime('%Y-%m-%d')
                    except ValueError:
                        date = date_time
                        dt = None
                    
                    if date not in date_groups:
                        date_groups[date] = []
                    date_groups[date].append((date_time, value_data['value'], dt))
                
                # 对每个日期，取时间最晚的值
                for date, records in date_groups.items():
                    if records:
                        # 按时间排序，取最后一个
                        if any(dt is not None for _, _, dt in records):
                            # 有有效的时间戳，按时间排序
                            records.sort(key=lambda x: x[2] if x[2] is not None else datetime.min)
                            unified_data[date][record_type] = records[-1][1]
                        else:
                            # 没有有效时间戳，取最后一个
                            unified_data[date][record_type] = records[-1][1]
            elif record_type in average_types:
                # 对于需要计算平均值的类型（如心率），计算平均值
                for date, value_data in dates_values.items():
                    if value_data['count'] > 0:
                        avg_value = value_data['sum'] / value_data['count']
                        # 心率输出为整数
                        unified_data[date][record_type] = int(round(avg_value))
            else:
                # 对于普通类型，直接使用聚合值
                for date, value_data in dates_values.items():
                    if record_type in ('FlightsClimbed', 'StepCount'):
                        # FlightsClimbed 和 StepCount 输出为整数
                        unified_data[date][record_type] = int(round(value_data['value']))
                    else:
                        unified_data[date][record_type] = round(value_data['value'], 1)
        
        # 写入统一的 CSV 文件
        output_path = os.path.join(self.directory, 'apple_health.csv')
        with open(output_path, 'w') as f:
            # 写入表头
            header = ['Date'] + RECORDS
            f.write(','.join(header) + '\n')
            
            # 写入数据
            for i, date in enumerate(sorted_dates):
                row = [date]
                for record_type in RECORDS:
                    value = unified_data[date][record_type]
                    if value is None:
                        row.append('')
                    else:
                        # FlightsClimbed、StepCount 和 HeartRate 输出为整数格式
                        if record_type in ('FlightsClimbed', 'StepCount', 'HeartRate'):
                            row.append(str(int(value)))
                        else:
                            row.append(str(value))
                # 最后一行不添加换行符
                if i == len(sorted_dates) - 1:
                    f.write(','.join(row))
                else:
                    f.write(','.join(row) + '\n')
        
        self.report(f'Written unified CSV file: {output_path}')

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
        print('USAGE: python3 export_apple_health.py /path/to/export.xml',
              file=sys.stderr)
        sys.exit(1)
    data = HealthDataExtractor(sys.argv[1])
    data.report_stats()
    data.export_unified_csv()
