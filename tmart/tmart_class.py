



# T-MART: Topography-adjusted Monte-Carlo Adjacency-effect Radiative Transfer code  



import random
from multiprocessing import Pool, cpu_count
from pathos.multiprocessing import ProcessingPool
# import tqdm
import numpy as np
import time
from copy import deepcopy
import math 

# from Surface import Surface
from .tm_sampling import sample_distance2scatter, sample_Lambertian
from .tm_geometry import dirP_to_coord, linear_distance, dirC_to_dirP, rotation_matrix, angle_3d, dirC_to_coord
from .tm_intersect import find_atm, intersect_line_DEMtri
from .tm_intersect import intersect_line_boundary, reflectance_intersect, reflectance_background, intersect_background
from .tm_water import find_R_wc, RefraIdx


# plotting 
import matplotlib
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d import axes3d
from mpl_toolkits.mplot3d.art3d import Poly3DCollection



def _track_job(job, update_interval=2):
    '''
    Track progress in multiprocessing 

    '''
    
    while job._number_left > 0:
        print("Tasks remaining = {0}".format(job._number_left * job._chunksize))
        time.sleep(update_interval)




# A class that we are going to overwrite with additional info (see tm.py)
class Tmart_Class():
    '''Create a Tmart object. 
    
    Arguments:

    * ``Surface`` -- Surface object from the Surface module.
    * ``Atmosphere`` -- Atmosphere object from the Atmosphere module.

    Example usage::

      my_tmart = tmart.Tmart(Surface = my_surface, Atmosphere= my_atm)

    '''
    
    def __init__(self, Surface, Atmosphere):

        
        
        self.Surface = Surface
        self.Atmosphere = Atmosphere
        
        self.sensor_coords = None
        self.target_cell = None
        self.sun_dir = None
        self.print_on = False # print switch 
        self.plot_on = False  # don't turn it on for multiprocessing 
        
        self.target_pt_direction = [180,0] 
        
        self.wl = None
        self.atm_profile_wl = None # single wavelength 
        self.aerosol_SPF_wl = None 
        
        
        self.wind_speed = 10 # default 10 m/s
        self.wind_azi_avg = True # azimuthally averaged cox munk
        self.wind_dir = 0 # default azimuthal, 0 means UPWIND along x-axis
            # AKA the direction where wind comes from 
           
        self.F_wc_wl = None # fraction of sea surface covered by whitecaps 
        self.R_wc_wl = None # whitecap reflectance at this wavelength
        
        self.water_salinity = 0
        self.water_temperature = 25      
        self.water_refraIdx_wl = None # refractive index of water at this wavelength 
        
        self.output_flux = False # output irradiance reflectance, direct irradiance and diffuse irradiance on the ground, to be continued 
        
        
             
        
    def set_geometry(self,sensor_coords=None,target_cell=None,
                     sun_dir=[0,0], target_pt_direction=None):
        '''Set geometry
        
        Arguments:

        * ``sensor_coords`` -- Where the sensor is, in [X, Y, Z], unit in meters.
        * ``sun_dir`` -- Solar angle, in [Zenith, Azimuth], relative to the target.
        * ``target_pt_direction`` -- Were to shoot photon from the sensor, AKA viewing angle, in [Zenith, Azimuth], relative to the sensor.

        Example usage::

          my_tmart.set_geometry(sensor_coords=[51,50,130_000], 
                      target_pt_direction=[180,0],
                      sun_dir=[0,0])

        '''
        
        
        # Sensor coordinates 
        if sensor_coords==None:
            self.sensor_coords = np.array([4500,4501,100_000]) 
        else:
            if sensor_coords[0]==sensor_coords[1]: sensor_coords[1]=sensor_coords[1]+0.0001
            
            self.sensor_coords = np.array(sensor_coords)
        
        # Target cell: [x1,y1,x2,y2]
        if target_cell==None:  # default 1, 1???
            self.target_cell = [0,0,1000,1000] # calculate using cell_size!!!
        else:
            self.target_cell = [0,0,1000,1000] # calculate using cell_size!!!
            
        # Lock photon initial direction 
        self.target_pt_direction = target_pt_direction   # Make it a function of self.target_cell!!!
        # Actually 2 values, one based on the cell, other specify 
        
        # Sun direction 
        self.sun_dir = sun_dir # [zenith, azimuthal]        
        
    def set_wind(self,wind_speed=10,wind_azi_avg=True,wind_dir=0): 
        '''Set wind speed and direction. 
        
        Arguments:

        * ``wind_speed`` -- wind speed in meters, default 10.
        * ``wind_azi_avg`` -- cox-munk slopes azimuthally averaged, default True.
        * ``wind_dir`` -- upwind direction clockwise from east, default 0. Meaningless when wind_azi_avg is True.

        Example usage::
          
          my_tmart.set_wind(wind_speed=5)
          my_tmart.set_wind(wind_speed=5, wind_azi_avg = False, wind_dir=0)
          
        '''
        
        self.wind_speed = wind_speed
        self.wind_dir = wind_dir
        self.wind_azi_avg = wind_azi_avg
        
    def set_water(self,water_salinity=0,water_temperature=25): # default 0/1000 and 25C
        '''Set water salinity and temperature. 
        
        Arguments:

        * ``water_salinity`` -- water salinity in parts per thousand, default 0.
        * ``water_temperature`` -- water temperature in celsius, default 25.

        Example usage::

          my_tmart.set_water(water_salinity=35, water_temperature=20)
          
        '''
        self.water_salinity = water_salinity
        self.water_temperature = water_temperature
        
    def _info(self): # to be continued...
    
    
        print("\n------- Displaying Information -------")

        print("\n=== sensor_coords ")
        print(self.sensor_coords)    
        
        print("\n=== target_cell ")
        print(self.target_cell)  
        
        print("\n=== sun_dir ")
        print(self.sun_dir)  


    def _init_atm(self): 
        
        if self.sensor_coords is None:
            print ("WARNING: geometry missing, set_geometry before you run")
        else:
            self.atm_profile_wl, self.aerosol_SPF_wl = self.Atmosphere._wavelength(self.wl)
            self.F_wc_wl, self.R_wc_wl = find_R_wc(wl=self.wl, wind_speed = self.wind_speed)
            self.water_refraIdx_wl = RefraIdx(self.water_salinity,self.water_temperature,self.wl)
            # self.water_refraIdx_wl = 1.34
            
            
            # test modifying atm. 
            # self.atm_profile_wl.ot_abs = 0.0000001
            # self.atm_profile_wl.ot_rayleigh = 0.3601303
            
            


    # User interface 
    def run(self, wl, n_photon=10_000,nc=None, njobs=80, print_on=False, output_flux=False): 
        '''Run with multiple processing 
        
        Arguments:

        * ``wl`` -- wavelength in nm.
        * ``n_photon`` -- number of photons to use in MC simulation, default 10,000.
        * ``nc`` -- number of CPU cores to use in multiprocessing, default automatic. 
        * ``njobs`` -- dividing the jobs into n portions in multiprocessing, default 80. 
        
        Return:

        * Movement information of photons.
        
        Example usage::

          n_photon = 100_00
          nc = 10
          njobs = 100
          results = my_tmart.run(wl=wl, n_photon=n_photon,nc= nc,njobs= njobs)
          
        '''
        
        self.wl = wl 
        self.print_on = print_on
        self.plot_on = False # don't even try it 
        self.output_flux = output_flux
        self._init_atm()
        
        
        if nc==None:
            nc = cpu_count()
        else:
            nc = nc
            
        print("\n========= Initiating T-Mart =========")
        print(f"Number of photons: {n_photon}")
        print(f'Using {nc} core(s)')
        
        n = n_photon
        
        
        part_count = [n/njobs for i in range(njobs)]
        
        part_count = np.array_split(range(n_photon), njobs)
        
        
        print(f"Number of job(s): {njobs}")
        print('Wavelength: ' + str(self.wl))
        print('target_pt_direction: ' + str(self.target_pt_direction))
        print('sun_dir: ' + str(self.sun_dir))
        print("=====================================")
        
        # nc = 16

        pool = ProcessingPool(processes=nc)
        time.sleep(0.5)
        
        
        # old
        # results = pool.amap(self._run,part_count).get() # Async
        
        
        # manual print 
        results_temp = pool.amap(self._run,part_count) # Async
        if njobs>1:
            _track_job(results_temp)
        results = results_temp.get() 
        
        
        
        # pool.close() # only map needs this, amap is good

        return results 

        
    # Distribute runs to processors     
    def _run(self,part_count):
    
        pts_stat = np.empty([0,12])
        # pts_stat = np.empty([0,1]) # for surface irradiance 
        
        for i in part_count:
            
            if self.print_on:
                print("\n---------- Running Photon " + str(i) + " ----------")
            
            pt_stat = self._run_single_photon(i)
            pts_stat = np.vstack([pts_stat, pt_stat])
          
      
        return pts_stat
    
    
    def run_plot(self, wl, plot_on=True, plot_range=None): 
        '''Run a single photon and plot, print the details of photon movements. 
        
        Arguments:

        * ``wl`` -- wavelength in nm.
        * ``plot_on`` -- Boolean, if plot the movements. 
        * ``plot_range`` -- List, [xmin, xmax, ymin, ymax, zmin, zmax]
        
        Return:

        * Movement information of a photon.

        Example usage::

          results = my_tmart.run_plot(wl=wl, plot_on=True, plot_range=[0,100_000,0,100_000,0,100_000])
          
        '''
        
        
        print("\n====== Running and Plotting T-Mart Single Photon ======")
        self.wl = wl 
        self.print_on = True    # Always print
        self.plot_on = plot_on  # Default plot, may turn off 
        if plot_range==None:
            plot_range = [0,100_000,0,100_000,0,100_000]
        self.plot_range = plot_range
            
        self._init_atm()
        
        
        
        
        ### Extract stats from results??? 
        
        return self._run_single_photon(0)
    
    
    # A single photon run, is overwritten in tm.py
    def _run_single_photon(self):
        return None


    # finds OT between TOA and z
    
    def _local_est_OT(self,q_collision): 
        # print('OT_abs of entire atm: {}'.format(sum(self.atm_profile_wl.ot_abs)))
        
        # Altitude of the collision point  
        z = q_collision[2]
 
        # Find all layers whose bottoms are equal to or higher than z, panda series Boolean 
        alts_higher = np.array(self.atm_profile_wl.Alt_bottom *1000 >= z)
        # print ('alts_higher: ' +str(alts_higher))
        
        

        # Calculate OTs in layers above, capital is output 
        OT_out = (sum(self.atm_profile_wl.ot_abs[alts_higher]) +  
                      sum(self.atm_profile_wl.ot_rayleigh[alts_higher]) + 
                      sum(self.atm_profile_wl.ot_mie[alts_higher]) )   
        # print ('OT_abs_out, sum of all above: ' +str(OT_abs_out))


        # boolean if equal 
        alts_equal = np.array( self.atm_profile_wl.Alt_bottom * 1000 == z )
        # print ('alts_equal: ' +str(alts_equal))
        # print ('sum alts_equal: ' +str(sum(alts_equal)))
        
        if sum(alts_equal): 
            # print('Find euqal altitude')
            pass
        else: # Alternative: find the layer where Z is in, find OT_remain_ratio...
            # print('No equal altitudes, calculating remaining OT_abs')
            
            # calculate top altitudes - collision altitude
            alts_diff = (self.atm_profile_wl.Alt_top - z/1000)
            # print ('alts_diff: ' +str(alts_diff))
            
            alts_diff_positive_min = alts_diff[alts_diff>0].min()
            # print ('alts_diff_positive_min: ' +str(alts_diff_positive_min))
            
            
            # edited 
            alts_diff_positive_min_idx = alts_diff[alts_diff>0].idxmin()
            # print ('alts_diff_positive_min_idx: ' +str(alts_diff_positive_min_idx))   
            
            height = self.atm_profile_wl.Alt_top[alts_diff_positive_min_idx] - self.atm_profile_wl.Alt_bottom[alts_diff_positive_min_idx]
            
            
            OT_remain_ratio = alts_diff_positive_min / height
            # print ('OT_remain_ratio: ' +str(OT_remain_ratio))            
            
            
            
            
            OT_layer = (self.atm_profile_wl.ot_abs[alts_diff_positive_min_idx] + 
                        self.atm_profile_wl.ot_rayleigh[alts_diff_positive_min_idx] + 
                        self.atm_profile_wl.ot_mie[alts_diff_positive_min_idx]  ) 
            
            # OT_layer = (self.atm_profile_wl.ot_scatt[alts_diff_positive_min_idx]  ) # test         
            
            
            # print ('ot_abs: ' +str(ot_abs))
            
            OT_abs_remain = OT_layer * OT_remain_ratio 
            # print ('OT_abs_remain: ' +str(OT_abs_remain))
            
            OT_out = OT_out + OT_abs_remain
        return OT_out


    def _local_est_OT_temp(self,q_collision):
        
        pass




    def _plot(self,q0,q1, scenario, intersect_tri_chosen=None, rotated=None, q_collision_N=None, specular_on=False, rotated_cm=None):
        fig = plt.figure()
        ax = Axes3D(fig, auto_add_to_figure=False)
        fig.add_axes(ax)
        
        #ax.invert_xaxis()
        
        
        # ax.set_xlim(0, 100_000 * 1) 
        # ax.set_ylim(100_000 * 1, 0 )
        # ax.set_zlim(0, 100_000 * 1 )   
        
        ax.set_xlim(self.plot_range[0],self.plot_range[1]) 
        ax.set_ylim(self.plot_range[3],self.plot_range[2])
        ax.set_zlim(self.plot_range[4],self.plot_range[5])   
        
        
        ax.set_xlabel('X axis (m)')
        ax.set_ylabel('Y axis (m)')
        ax.set_zlabel('Z axis (m)')
        
        
        # Plotting DEM_tri
        for tri in self.Surface.DEM_triangulated:
            for row in range (0, tri.shape[2]):
                for col in range (0, tri.shape[3]):
                    # print (row, col)
            
                    p0 = tri[0,:,row,col] 
                    p1 = tri[1,:,row,col]
                    p2 = tri[2,:,row,col]
                    
                    plot_tri = [p0,p1,p2]
                    
                    # print("------")
                    # print('plot_tri: ' + str(plot_tri))
                    
                    p_centre = (p0 + p1 + p2)/3
                    # print('p_centre: ' + str(p_centre))
                    
                    q_collision_ref = reflectance_intersect(p_centre, self.Surface.reflectance, 
                                                            self.Surface.cell_size, self.Surface.bg_ref, 
                                                            self.Surface.bg_coords)    
                    # print('q_collision_ref: ' + str(q_collision_ref))
                    
                    if q_collision_ref>1: q_collision_ref=1
                    if q_collision_ref<0: q_collision_ref=0
                    
                    
                    poly = Poly3DCollection(plot_tri,
                                #facecolors='ivory',
                                facecolors=str(q_collision_ref),
                                linewidths=0.3,
                                edgecolors='black',
                                alpha=0.9
                                )
                    ax.add_collection3d(poly)
        

        x=[q0[0],q1[0]]
        y=[q0[1],q1[1]]
        z=[q0[2],q1[2]]
        
        cols = ['cyan','paleturquoise','honeydew','mistyrose','tomato','red']
        # cols = ['cyan','paleturquoise','honeydew','blue','blue','blue']
        n_cols = 6
        
        for i in range(n_cols):
            ax.plot([x[0] + (x[1]-x[0]) /n_cols *i  ,  x[0] + (x[1]-x[0])/n_cols*(i+1)],
                    [y[0] + (y[1]-y[0]) /n_cols *i  ,  y[0] + (y[1]-y[0])/n_cols*(i+1)],
                    zs=[z[0] + (z[1]-z[0]) /n_cols *i  ,  z[0] + (z[1]-z[0])/n_cols*(i+1)],
                    color=cols[i],
                    zorder=100)

        if scenario==1:
            
            # Manual length of the other two lines 
            my_length = 35000
            # my_length = 1
            
            
            if self.print_on: print ("\nPlotting triangle collision")
        
            triangle = intersect_tri_chosen.tolist()
            
            # convert normal_direction to normal_coordinates
            if specular_on:
                color_normal = 'blue'
                triangle[3:6] = dirC_to_coord(rotated_cm,triangle[0:3],my_length)
            else:
                color_normal = 'lime'
                triangle[3:6] = dirC_to_coord(triangle[3:6],triangle[0:3],my_length)
                
            # normal 
            ax.plot([triangle[0] , triangle[3]],
                    [triangle[1] ,  triangle[4]],
                    zs=[triangle[2] ,  triangle[5]],
                    color = color_normal,
                    zorder=100
                    )
            
            # reflected direction 
            reflected_viz_q1 = triangle[0:3] + rotated*35000
            # print('==============================')
            # print(reflected_viz_q1)
            

            # new pt_direction 
            
            ax.plot([triangle[0] , reflected_viz_q1[0]],
                    [triangle[1] ,  reflected_viz_q1[1]],
                    zs=[triangle[2] ,  reflected_viz_q1[2]],
                    color = 'orange',
                    zorder=100
                    )
            
            if self.print_on: print("Angle between normal and new pt_direction is: " + 
                                    str(angle_3d(rotated,[0,0,0],q_collision_N)))
        
    
        # Plot atmospheres to the same extend as the surface 
        
        plt.show()












