import time

import requests
from werkzeug import urls
import ray
from ray.experimental import serve
from ray.experimental.serve.utils import pformat_color_json
import json
from ray.experimental.serve.utils import BytesEncoder
from torchvision.models.resnet import resnet50
import io
from PIL import Image
from torch.autograd import Variable
import torchvision.transforms as transforms
import base64
from pprint import pprint
import torch
import asyncio
import queue
class RequestRecorder:
	def __init__(self,queue):
		self.queue = queue
		self.timing_stats = {}
		self.pending_futures = []
	async def examine_futures(self):
		await asyncio.sleep(0.0009)
		print("Started")
		while True:

			# await asyncio.sleep(0.5)
			new_pending_futures = []
			if self.queue.qsize() > 0:
				# while not self.queue.empty():
				try:
					item  = self.queue.get(block=True,timeout=0.009)
					new_pending_futures.append(item)
				except Exception:
					break
					
			else:
				if len(self.pending_futures) == 0:
					break
			self.pending_futures = self.pending_futures + new_pending_futures
			# print("PENDING FUTURES: {}".format(self.pending_futures))
			completed_futures , remaining_futures = ray.wait(self.pending_futures,timeout=0.001)
			if len(completed_futures) == 1:
				f = completed_futures[0]
				self.timing_stats[f] = time.time()
			self.pending_futures = remaining_futures
		print("ended")
		return

async def send_queries(query_list,pipeline_handle,future_queue,associated_query):
	for q in query_list:
		q['start_time'] = time.time()
		f = pipeline_handle.remote(**q['data'])
		future_queue.put_nowait(f)
		associated_query[f] = q
	






def query():
	d = {
	'index': '',
	'start_time': '',
	'end_time': '',
	'slo': '' ,
	'data': ''
	    }
	return d

class Transform:
	def __init__(self,transform):
		self.transform = transform
	def __call__(self,batch_data):
		batch_size = len(batch_data)
		result = []
		for i in range(batch_size):
			data = Image.open(io.BytesIO(base64.b64decode(batch_data[i])))
			if data.mode != "RGB":
				data = data.convert("RGB")
			data = self.transform(data)
			# data = data.unsqueeze(0)
			result.append(data)
		return result

class Resnet50:
	def __init__(self, model):
		self.model = model

	def __call__(self, batch_data):
		# if 'transform' in context:
		# data = context['transform']
		data = torch.stack(batch_data)
		data = Variable(data)
		data = data.cuda()
		outputs = self.model(data)
		_, predicted = outputs.max(1)
		return predicted.cpu().numpy().tolist()


min_img_size = 224
transform = transforms.Compose([transforms.Resize(min_img_size),
                                         transforms.ToTensor(),
                                         transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                                              std=[0.229, 0.224, 0.225])])
model = resnet50(pretrained=True)
model = model.cuda()

serve.init(object_store_memory=int(1e9),blocking=True)
#create Backends
serve.create_backend(Transform, "transform:v1",0,transform)
serve.create_backend(Resnet50,"r50",1,model)

# create service
serve.create_no_http_service("transform",max_batch_size=2)
serve.create_no_http_service("imagenet-classification",max_batch_size=4)

#link service and backend
serve.link_service("transform", "transform:v1")
serve.link_service("imagenet-classification", "r50")

serve.add_service_dependencies("pipeline1","transform","imagenet-classification")

# Provision the PIPELINE (You can provision the pipeline only once)
serve.provision_pipeline("pipeline1")


dependency = serve.get_service_dependencies("pipeline1")
pipeline_handle = serve.get_handle("pipeline1")


future_list = []
query_list = []
query_list = []

for r in range(40):
	q = query()
	q['slo'] = 70
	q['index'] = r
	req_json = { "transform": base64.b64encode(open('../elephant.jpg', "rb").read()) }
	req_json['slo'] = q['slo']
	q['data'] = req_json
	query_list.append(q)

future_queue = queue.Queue()
reqRecord = RequestRecorder(queue=future_queue)
associated_query = {}
loop = asyncio.get_event_loop()
task1 = asyncio.ensure_future(reqRecord.examine_futures())
task2 = asyncio.ensure_future(send_queries(query_list,pipeline_handle,future_queue,associated_query))

loop.run_until_complete(asyncio.wait([task1,task2]))
loop.close()

for f in associated_query.keys():
	val = associated_query[f]
	end_time = reqRecord.timing_stats[f]
	val['end_time'] = end_time
for f in associated_query.keys():
	print("-----------------")
	val = associated_query[f]
	print("Query Index: {}  time taken (in seconds): {}".format(val['index'],(val['end_time']-val['start_time'])))


