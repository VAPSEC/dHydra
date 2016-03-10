# -*- coding: utf8 -*-
"""
股票接口类 
Created on 02/17/2016
@author: Wen Gu
@contact: emptyset110@gmail.com
"""
from __future__ import print_function, absolute_import
from pymongo import MongoClient
from datetime import datetime, timedelta
from pandas import DataFrame
import tushare as ts
import time as t
import json
import pandas
from .config import const as C
from . import util
import threading
import asyncio
import os

class Stock:

	def __init__(self):
		self.loop = asyncio.get_event_loop()
		# connect to mongodb named: stock
		client = MongoClient()
		self.db = client.stock
		self.outstanding = list()
		# INITIALIZATION: CHECKING UPDATES
		print( "Checking Updates..." )
		self.update_basic_info()
		[self.codeList, self.symbolList, self.basicInfo] = self.fetch_basic_info()
		self.sina = None


	## NOT IN USE ##
	def fetch_classification(self):
		# 数据来源自新浪财经的行业分类/概念分类/地域分类
		print( "Trying: get_today_all" )
		today_all = ts.get_today_all() #一次性获取今日全部股价
		set_today_all = set(today_all.T.values[0])

		print( "Trying: get_industry_classified" )
		industry_classified = ts.get_industry_classified()
		set_industry_classified = set(industry_classified.T.values[0])

		print( "Trying: get_area_classified" )
		area_classified = ts.get_area_classified()
		set_area_classified = set(area_classified.T.values[0])

		print( "Trying: get_concept_classified" )
		concept_classified = ts.get_concept_classified()
		set_concept_classified = set(concept_classified.T.values[0])

		print( "Trying: get_sme_classified" )
		sme_classified = ts.get_sme_classified()
		set_sme_classified = set(sme_classified.T.values[0])

		return [
					today_all
				,	set_today_all
				,	industry_classified
				,	set_industry_classified
				,	area_classified
				,	set_area_classified
				,	concept_classified
				,	set_concept_classified
				,	sme_classified
				,	set_sme_classified
				]

	# Will automatically call "update_basic_info" if needed
	# @return [self.codeList, self.symbolList, self.basicInfo]
	def fetch_basic_info(self):
		result = self.db.basicInfo.find_one( 
			{
				"lastUpdated": {"$exists":True, "$ne": None}
			}
		)
		if (result != None):
			codeList = list(result["basicInfo"]["name"].keys())
		else:
			update_basic_info()
			[codeList, result] = self.fetch_basic_info()

		symbolList = list()
		for code in codeList:
			symbolList.append( util._code_to_symbol(code) )

		self.updated = datetime.now()
		return [codeList, symbolList, result]

	# Update stock.basicInfo in mongodb
	def update_basic_info(self):
		update_necessity = False
		basicInfo = self.db.basicInfo.find_one( 
			{
				"lastUpdated": {"$exists":True, "$ne": None}
			}
		)
		if (basicInfo == None):
			print( "No record of basicInfo found. A new record is to be created......" )
			update_necessity = True
		else:
			# Criteria For Updating
			if ( ( basicInfo["lastUpdated"].date()<datetime.now().date() ) ):
				update_necessity = True
				print( "Stock Basic Info last updated on: ", basicInfo["lastUpdated"], "trying to update right now..." )
			elif ( basicInfo["lastUpdated"].hour<9 ) & ( datetime.now().hour>=9 ) :
				update_necessity = True
				print( "Stock Basic Info last updated on: ", basicInfo["lastUpdated"], "trying to update right now..." )
			else:
				print( "Stock Basic Info last updated on: ", basicInfo["lastUpdated"], " NO NEED to update right now..." )
			
		if (update_necessity):
			basicInfo = ts.get_stock_basics()
			
			result = self.db.basicInfo.update_one(
				{
					"lastUpdated": {"$exists": True, "$ne": None}
				},
				{
					"$set": {
						"lastUpdated": datetime.now(),
						"basicInfo": json.loads(ts.get_stock_basics().to_json()),
						"codeList": list(basicInfo.index)
					}
				},
				upsert = True
			)

	def self_updated(self,code):
		num = len(code)
		# TODO: UGLY HERE. Need a better logic for updating
		if ( ( self.updated.date() == datetime.now().date() ) & ( self.updated.hour >= 9 ) ):
			if ( self.outstanding == [] ):
				for i in range(0,num):
					self.outstanding.append( self.basicInfo["basicInfo"]["outstanding"][code[i]] )
		else:
			print( "The basicInfo is outdated. Trying to update basicInfo..." )
			self.update_basic_info()
			[ self.codeList, self.basicInfo ] = self.fetch_basic_info()
			self.outstanding = list()
			for i in range(0,num):
				self.outstanding.append( self.basicInfo["basicInfo"]["outstanding"][code[i]] )

	# fetch realtime data using TuShare
	#	Thanks to tushare.org
	def fetch_realtime(self):
		i = 0
		while ( self.codeList[i:i+500] != [] ):
			if (i==0):
				realtime = ts.get_realtime_quotes( self.codeList[i : i+500] )
			else:
				realtime = realtime.append( ts.get_realtime_quotes( self.codeList[i : i+500] ), ignore_index=True )
			i += 500

		# Get the datetime
		data_time = datetime.strptime( realtime.iloc[0]["date"] + " " + realtime.iloc[0]["time"] , '%Y-%m-%d %H:%M:%S')
		code = realtime["code"]
		realtime["time"] = data_time
		# Drop Useless colulmns
		realtime = realtime.drop( realtime.columns[[0,6,7,30]] ,axis = 1)
		# Convert string to float
		realtime = realtime.convert_objects(convert_dates=False,convert_numeric=True,convert_timedeltas=False)
		# update self.basicInfo & self.outstanding
		self.self_updated(code)
		# Compute turn_over_rate
		realtime["turn_over_ratio"] = realtime["volume"]/self.outstanding/100
		realtime["code"] = code

		return realtime

	# First fetch_realtime, then insert it into mongodb
	def get_realtime(self,time):
		realtime = self.fetch_realtime()

		data_time = realtime.iloc[0]['time']
		if (data_time>time):
			time = data_time
		else:
			print( "No need", time )
			return data_time

		self.db.realtime.insert_many( realtime.iloc[0:2900].to_dict(orient='records') )
		print( "data_time", data_time )
		return time

	def start_realtime(self):
		time = datetime.now()
		while True:
			try:
				start = datetime.now()

				if (start.hour<9 or start.hour>15):
					print( "It's Too Early or Too late", start )
					t.sleep(360)
					continue
				time = self.get_realtime( time )
				print( "time cost:", (datetime.now()-start) )
			except Exception as e:
				print( e )

	def export_realtime_csv(	self
							,	date=None
							,	end=str( (datetime.now()+timedelta(days=1)).date() )
							,	resample=None,	prefix=''
							,	path=C.PATH_DATA_ROOT+C.PATH_DATA_REALTIME
							):
		total_len = len(self.codeList)
		start_time = datetime.now()

		if date==None:
			s_date = input('Please input the date(Format:"2016-02-16"):')
		else:
			s_date = date

		# import os
		try:
		    os.makedirs( "%s%s" % ( path,s_date ), exist_ok=True )
		except Exception as e:
			print(e)
			try:
				os.makedirs( "%s%s" % ( path,s_date ) )
			except Exception as e:
				print(e)
				pass
		date = datetime.strptime(s_date, '%Y-%m-%d')

		for i in range(0,total_len):

			items = list()
			# print( type(self.codeList[i]) )
			stock_cursor = self.db.realtime.find(
				{
					"code": self.codeList[i]
				,	"time": { "$gt": date, "$lt" : date + timedelta(days=1) }
				}
			)

			if (stock_cursor.count() == 0):
				continue

			for row in stock_cursor:
				items.append(row)

			stock_csv = pandas.DataFrame.from_dict(items)

			stock_csv["turn_over_ratio"] = stock_csv["volume"]/self.basicInfo["basicInfo"]["outstanding"][ self.codeList[i] ]/100

			stock_csv.set_index("time",drop=False,inplace=True)
			if (resample!=None):
				stock_csv = stock_csv.resample(resample,how='last')
			upper_bound = datetime.strptime( s_date+" "+'09:15:00' , '%Y-%m-%d %H:%M:%S')
			lower_bound = datetime.strptime( s_date+" "+'15:05:00' , '%Y-%m-%d %H:%M:%S')
			stock_csv = stock_csv[(stock_csv.time>upper_bound) & (stock_csv.time<lower_bound)]
			stock_csv.to_csv( 	'%s%s/%s.csv'% (path,s_date,self.codeList[i])
							,	columns = [	
											"volume"
										,	"amount"
										,	"price"
										,	"b1_ratio"
										,	"a1_p",	"a1_v"
										,	"a2_p",	"a2_v"
										,	"a3_p",	"a3_v"
										,	"a4_p",	"a4_v"
										,	"a5_p",	"a5_v"
										,	"b1_p",	"b1_v"
										,	"b2_p",	"b2_v"
										,	"b3_p",	"b3_v"
										,	"b4_p",	"b4_v"
										,	"b5_p",	"b5_v"
										,	"open",	"pre_close"
										,	"turn_over_ratio"
										]
			)

			print("time cost:",( datetime.now()-start_time ) )
			print("Process: ",float(i)/float(total_len)*100, "%")

	"""
	下面是调用新浪部分
	"""
	def get_sina(self):
		from . import sinaFinance
		self.sina = sinaFinance.SinaFinance()
		return self.sina

	# 开启新浪L2 Websocket
	def start_sina(self, callback=None):
		if (self.sina is None):
			self.get_sina()

		if not(self.sina.isLogin):
			print("新浪没有登录成功，请重试")
			return False

		threads = []
		# Cut symbolList
		step = 50
		symbolListSlice = [self.symbolList[ i : i + step] for i in range(0, len(self.symbolList), step)]
		for symbolList in symbolListSlice:

			loop = asyncio.get_event_loop()
			if loop.is_running():
				loop = asyncio.new_event_loop()
				asyncio.set_event_loop( loop )

			t = threading.Thread(target = self.sina.start_ws,args=(symbolList,loop,callback) )
			threads.append(t)
		for t in threads:
			t.setDaemon(True)
			t.start()
			print("开启线程：",t.name)
		for t in threads:
			t.join()

	# thread_num代表同时开启的线程数量，默认15个
	def sina_l2_hist(self, thread_num = 15):
		if (self.sina is None):
			self.get_sina()
		if not(self.sina.isLogin):
			print("新浪没有登录成功，请重试")
			return False
		threads = []
		step = int( len(self.codeList)/thread_num )
		symbolListSlice = [self.symbolList[ i : i + step] for i in range(0, len(self.symbolList), step)]
		for symbolList in symbolListSlice:

			loop = asyncio.get_event_loop()
			if loop.is_running():
				loop = asyncio.new_event_loop()
				asyncio.set_event_loop( loop )

			t = threading.Thread(target = self.sina.l2_hist_list, args=(symbolList,loop,) )
			threads.append(t)

		for t in threads:
			t.setDaemon(True)
			t.start()
			print("开启线程：",t.name)
		for t in threads:
			t.join()